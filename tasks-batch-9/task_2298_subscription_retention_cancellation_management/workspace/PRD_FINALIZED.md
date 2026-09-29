# Subscription Retention & Cancellation Management API — Product Requirements Document

## 1. Introduction

A direct-to-consumer subscription brand loses money in two very different ways, and for years our tooling has treated them as one. A subscriber who clicks "cancel" because the box arrives too often is a retention problem: the right answer is a pause, a skip, a smaller plan or a temporary discount, offered once, honestly, and without burying the cancel button behind five screens. A subscriber whose card silently expires is a collections problem: the right answer is a retry schedule, a card-updater request and a grace window sized to how long they have been a customer. Conflating the two produces the worst of both worlds — we chase loyal customers with discounts they did not need, and we let good customers churn because nobody asked their bank for a new card number.

This document specifies the API that separates those two paths and makes each of them auditable. It governs the plan and offer catalogue, subscriber and payment-method records, the two-axis subscription lifecycle, invoicing and dunning, the cancellation conversation with its reason capture and single save-offer round, the margin guardrails that stop retention from giving away contribution margin, the statutory notice trail that a negative-option offer legally requires, win-back targeting for lapsed subscribers with its suppression rules, and the cohort analytics that tell us whether any of it worked.

Two design commitments run through every requirement below. The first is the **simple-cancellation guarantee**: a subscriber who starts a cancellation must always be able to finish it, within a hard budget of recorded steps, no matter what the retention flow would prefer. The second is **separation of duties on money**: the retention operator who presents a below-floor offer can never be the compliance reviewer who authorises it. Both commitments are enforced by the server, not by client convention, and both are expressed below as concrete rejections with concrete error identifiers.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold everywhere in the API: authentication, the response envelope, pagination, resource identity, arithmetic precision, concurrency control, validation ordering, the two-axis state model, and the compliance and conservation invariants that later sections lean on.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the five role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the declared role is not authorised for the operation being invoked, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five recognised roles are `Subscriber`, `RetentionSpecialist`, `BillingOperator`, `ComplianceOfficer`, and `PlatformAdmin`.

- `Subscriber` is the end customer. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber` entity; ownership checks on any resource that references a `Subscriber` compare the resource's `subscriber_id` — reached directly, or indirectly through the subscription, invoice, session, grant or modification the request touches — to `X-User-ID`. A `Subscriber` acting on another subscriber's resource chain is rejected with `ERR_UNAUTHORIZED` (HTTP 403). A `Subscriber` owns its own payment methods, subscriptions, modifications, cancellation sessions and save-offer responses, and its reads are scoped to its own resources.
- `RetentionSpecialist` is the retention operator: the only role that may present a save offer, and the role that runs win-back campaigns and reverses modifications. When `X-User-Role` is `RetentionSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — as `presented_by_user_id` on both the `CancellationSession` and the `SaveOfferGrant` produced by an offer-presentation round — but never compares it to any entity's `id`.
- `BillingOperator` is the collections operator: renewals, charge attempts, card-updater ingestion and compliance-notice sends. When `X-User-Role` is `BillingOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but does not compare it to any entity's `id`.
- `ComplianceOfficer` is the regulatory reviewer: the only role that may decide a margin-floor exception, and a role that may schedule statutory notices. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `decided_by_user_id` on the grant whose exception was decided, but does not compare it to any entity's `id`.
- `PlatformAdmin` is the configuration and test-harness operator: plans, save-offer templates, subscriber registration and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.

Because `RetentionSpecialist` and `ComplianceOfficer` identifiers are both opaque strings drawn from the same space, the segregation-of-duties rule is expressed as a direct string comparison: the `X-User-ID` of the `ComplianceOfficer` deciding a grant's margin-floor exception must differ from that grant's `presented_by_user_id`. When the two are equal the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and that check outranks every other guard on the exception decision.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, may not be below 1, and may not exceed 100. `offset` is the number of items to skip and defaults to 0.

Unless a particular endpoint says otherwise, every list is ordered by `created_at` ascending.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope described in §2.2.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource in the system is addressed by an `id` — a server-minted UUID string with no type prefix — and records a `created_at` timestamp, an ISO 8601 UTC instant rendered with exactly three fractional digits (for example `2026-08-01T00:00:00.000Z`).

Most resources additionally carry two mutation-tracking fields. `updated_at` is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every change to the resource. `version` is an integer that starts at 1 on creation and increments by one on every mutation of that resource, including mutations the server performs on its own initiative to keep derived state aligned. `Plan`, `Subscriber`, `Subscription`, `PaymentMethod`, `Invoice`, `CancellationSession`, `SaveOfferTemplate`, `SaveOfferGrant`, `SubscriptionModification`, `ComplianceNotice`, `WinBackCampaign` and `WinBackTarget` all carry `updated_at` and `version`.

Two resources are append-only records of something that already happened and therefore carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them entirely: `DunningAttempt`, which records one charge attempt against one invoice, and `RetentionCohortSnapshot`, which is an immutable analytical artifact with no update or delete operation of any kind.

All temporal reasoning in this system — tenure buckets, grace windows, reminder windows, offer expiry, suppression windows, trailing-window counts — reads a **logical clock**, never the host wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` moves it by supplying a `to_iso8601` instant to the clock-setting capability; every subsequent evaluation reads the new instant. Throughout this document, "the clock" and "now" mean this logical clock.

Computed fields on `Subscriber` deserve a specific note: they are derived at read time against the logical clock. Reading a subscriber therefore always reflects the current `tenure_days`, the current `tenure_bucket`, the current `realized_ltv_cents` and `projected_ltv_cents` pair and the current trailing-window counts, without any intervening write being required.

### 2.5. Nested Resource Retrieval and Existence Ordering

The entity graph is deliberately flat: peers are linked by explicit foreign keys carried in request bodies, and there is exactly one nested read path, `/subscriptions/{id}/compliance-notices`, which walks backwards from a subscription to the notices that reference it.

Where a path does contain more than one identifier, identifiers are resolved strictly left to right, and the request fails on the **first** unresolvable segment with that segment's own not-found code. Body-borne foreign keys are resolved after the path and before any business rule: `subscriber_id` failures yield `ERR_SUBSCRIBER_NOT_FOUND`, `plan_id`, `target_plan_id` and `downgrade_target_plan_id` failures yield `ERR_PLAN_NOT_FOUND`, `subscription_id` yields `ERR_SUBSCRIPTION_NOT_FOUND`, `payment_method_id` yields `ERR_PAYMENT_METHOD_NOT_FOUND`, `invoice_id` yields `ERR_INVOICE_NOT_FOUND`, and `winback_target_id` yields `ERR_WINBACK_TARGET_NOT_FOUND`. Path identifiers for the remaining resource types resolve to `ERR_CANCELLATION_SESSION_NOT_FOUND`, `ERR_SAVE_OFFER_GRANT_NOT_FOUND`, `ERR_SAVE_OFFER_TEMPLATE_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_COMPLIANCE_NOTICE_NOT_FOUND`, `ERR_WINBACK_CAMPAIGN_NOT_FOUND`, `ERR_DUNNING_ATTEMPT_NOT_FOUND` and `ERR_COHORT_SNAPSHOT_NOT_FOUND` respectively. All of these carry HTTP 404.

### 2.6. Validation Ordering

When a single request violates more than one rule, exactly one error is returned, and which one is not left to implementation taste. Checks are ranked, and the highest-ranked failing check determines the response. The global ranking runs in these bands, in order:

1. **Authentication** — headers present and role recognised (`ERR_UNAUTHENTICATED`, 401).
2. **Authorisation by role** — the acting role appears on the endpoint's role list (`ERR_UNAUTHORIZED`, 403).
3. **Path existence** — every path segment resolves, left to right (404 codes per §2.5).
4. **Body foreign-key existence** — every foreign key supplied in the body resolves; this covers `subscriber_id`, `plan_id`, `payment_method_id`, `subscription_id`, `target_plan_id` and `winback_target_id` (404 codes per §2.5).
5. **Request schema** — required fields present, enum members in range, integers non-negative, datetimes well-formed ISO 8601, and `cohort_month` matching a four-digit year, a hyphen and a two-digit month in the range 01 through 12 (`ERR_INVALID_REQUEST`, 400). This band applies to every write endpoint.
6. **Subscriber ownership** — when the acting role is `Subscriber`, `X-User-ID` equals the `subscriber_id` of the resource chain being touched (`ERR_UNAUTHORIZED`, 403). This band applies to payment-method attachment, subscription creation, modification requests, the marketing-preference update, cancellation-session creation, reason capture, cancellation completion, and both save-offer responses.
7. **Optimistic concurrency** — the supplied expected parent version matches the parent's current `version` (412 codes per §2.7).
8. **Segregation of duties** — the margin-exception decider differs from the presenter (`ERR_SEGREGATION_OF_DUTIES`, 403).
9. **Domain state, safety, temporal, constraint, fiscal and referential checks** — in the per-endpoint order stated alongside each workflow in §3.

Band 7 outranking band 9 has a consequence worth stating plainly: a modification request that is both stale and aimed at a subscription that can no longer be modified is rejected as stale, not as unmodifiable. The same applies to win-back targeting, where a stale campaign version outranks the campaign's own lifecycle state.

### 2.7. Optimistic Concurrency Control on Subscription and Campaign Writes

Two write operations require the client to prove it has seen the parent resource's latest state. Neither is optional, and no other endpoint in the system accepts a version field of any kind.

A modification request against a subscription must carry `expected_subscription_version`, holding the client's last observed `version` of that `Subscription`. If that value does not equal the subscription's current `version`, the request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). The reason is structural rather than cosmetic: a newly applied modification legitimately supersedes the plan, cadence, addon set and discount that the client read, so a writer holding a stale view would compute `prior_snapshot` and `delta_price_cents` from values the subscription no longer holds, and would silently break the price-conservation invariant of §2.9.

Adding a target to a win-back campaign must carry `expected_campaign_version`, holding the client's last observed `version` of that `WinBackCampaign`. A mismatch with the campaign's current `version` is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412). Every accepted target changes `targeted_count` and can flip the campaign into `CLOSED`, so a stale writer would be re-targeting subscribers against a roster it can no longer see.

### 2.8. Money, Margins and Rounding

Every monetary field in this system is an **integer count of cents**. There are no fractional-cent amounts anywhere: `monthly_price_cents`, `unit_cogs_cents`, `amount_cents`, `cogs_cents`, `committed_price_cents`, `baseline_price_cents`, `delta_price_cents`, `retention_value_cents`, `realized_ltv_cents`, `projected_ltv_cents` and `mean_ltv_cents` are all whole cents.

Every fractional field — `margin_floor_pct`, `active_discount_pct`, `discount_pct`, `offer_discount_pct`, `per_cycle_margin_pct`, `blended_term_margin_pct`, `retention_rate`, `proration_factor` and `priority_score` — is carried to exactly **four decimal places**.

The single rounding mode used everywhere in this system is **round half up**: a value exactly on the midpoint rounds away from zero. It applies when reducing a monetary product to whole cents, when reducing a ratio to four decimal places, and when reducing a cycle count to an integer.

One rounding *order* is pinned and must not be reordered, because the two readings give different answers. When an invoice total is assembled from a plan line and addon lines, **each line is rounded to whole cents first, and the rounded lines are then summed.** Summing the raw unrounded products and rounding the total once is the forbidden reading. The same ordering discipline applies to `committed_price_cents`, which rounds the plan component and each addon component separately before adding them.

Percentages are never stored as percentages: a thirty-five percent discount is the value `0.3500`, and a forty-two percent margin floor is `0.4200`. `margin_floor_pct` may be anywhere from `0.0000` through `1.0000` inclusive. `active_discount_pct`, `discount_pct` and `offer_discount_pct` are at least `0.0000` and strictly below `1.0000` — a full-price giveaway is not expressible.

### 2.9. The Two Conserved Quantities

Two quantities in this system are conserved, and both are auditable from stored rows rather than trusted to sequential mutation.

**Money.** A subscription records `baseline_price_cents`, which is its `committed_price_cents` as of creation and is never overwritten. Thereafter, the subscription's current `committed_price_cents` must always equal `baseline_price_cents` plus the sum of `delta_price_cents` across every `SubscriptionModification` on that subscription whose `state` is `APPLIED` or `REVERSED`. Rows in `SCHEDULED` or `CANCELLED` are excluded from that sum and always carry `delta_price_cents` of 0. A reversal does **not** erase the original row's delta: the original keeps its value and moves to `REVERSED`, and a compensating row is added carrying the exact arithmetic inverse, so a forward-plus-compensating pair leaves `committed_price_cents` where it started.

**Shipments.** A plan allots `shipments_per_term` shipment units to one subscription term. The subscription tracks how many of those have been consumed by renewals that actually issued an invoice (`term_shipments_delivered`) and how many were consumed by applied skips (`term_shipments_skipped`). `term_shipments_remaining` is always `shipments_per_term` minus those two counters — never an independently mutated number.

### 2.10. The Two Independent Subscription Axes

A `Subscription` runs two state machines at once, and they evolve from different triggers. Neither axis constrains the other, and a subscription may legitimately sit in any combination of the two — a paused subscription can be past due, and reading a subscription returns both axes.

The **lifecycle axis**, `lifecycle_state`, is the access-and-fulfilment axis. It begins at `ACTIVE` and takes values `ACTIVE`, `PAUSED`, `PENDING_CANCEL` and `CANCELLED`. `CANCELLED` is terminal.

The **billing axis**, `billing_state`, is the collections axis. It begins at `CURRENT` and takes values `CURRENT`, `PAST_DUE`, `GRACE` and `DELINQUENT`.

Whenever an operation moves either axis, or changes any stored field of the subscription, the subscription's `updated_at` is refreshed and its `version` increments by one. That includes server-initiated moves the client never asked for: the auto-resume of a lapsed pause, the finalisation of a due cancellation, the repointing of `payment_method_id` when a newer card is attached, and the cascades that follow a write-off. Because `version` participates in the concurrency check of §2.7, every one of those bumps invalidates a client's cached view.

Cascades in this system are immediate and complete within the request that triggers them. When one operation touches several entities, all of the touched entities are updated before the response is produced; there is no deferred reconciliation.

### 2.11. Negative-Option Compliance Posture

A plan whose `is_negative_option` flag is true auto-renews under a negative-option offer and is therefore subject to a disclosure requirement at signup and a renewal-reminder requirement at every renewal. A plan created with that flag omitted is treated as a negative-option plan: the default is true.

Compliance is recorded, not asserted. Each obligation produces a `ComplianceNotice` row whose `notice_type` is one of `NEGATIVE_OPTION_DISCLOSURE`, `RENEWAL_REMINDER`, `PRICE_CHANGE` or `CANCELLATION_CONFIRMATION`, whose `state` is `SCHEDULED`, `SENT` or `MISSED`, whose `channel` is `EMAIL` (the default) or `SMS`, and which may carry an optional `body_ref` pointing at the body template. `scheduled_for` is the instant the notice is due — supplied by the caller for manually scheduled notices and set by the server for system-created ones — and `sent_at` is the clock instant of the send, null while the notice is `SCHEDULED` or `MISSED`. Each notice also records `renewal_cycle_index`, the `cycle_index` of the upcoming renewal at the moment the notice was created, so that reminder obligations can be matched to the specific cycle they cover.

The renewal-reminder legal window is a **closed** interval. It opens `renewal_reminder_days_before` days before the subscription's `next_renewal_at` and closes exactly three days before `next_renewal_at` — the minimum reminder lead time, which is also the floor on `renewal_reminder_days_before` itself, so a plan may never be configured with a reminder lead shorter than three days. When `renewal_reminder_days_before` is omitted at plan creation it defaults to 10 days, giving a window that runs from ten days out to three days out inclusive. Both endpoints of the interval are inside the window.

A cooldown protects subscribers from duplicate statutory mail: a notice may not be sent when fewer than three days have elapsed since the `sent_at` of the most recent `SENT` notice sharing the same `notice_type` and the same `renewal_cycle_index`. The boundary is inclusive on the permitted side — a send exactly three days later is allowed. Compliance sends never touch `Subscriber.last_contacted_at`; that field tracks marketing contact only.

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalogue: Plans and Save-Offer Templates

Everything begins with a **Plan**, created by a `PlatformAdmin`. A plan is identified by a `code` — unique across all plans, and restricted to uppercase letters, digits and the underscore character — and carries a human-readable `name`. Its commercial shape is `monthly_price_cents`, the list price charged per shipment cycle, which must be strictly greater than zero, and `unit_cogs_cents`, the cost of goods per shipment, which must be zero or greater and which every margin calculation in this document reads. `shipments_per_cycle` is how many shipments one invoice cycle bills for; it must be at least 1 and defaults to 1. `shipments_per_term` is the shipment allotment for one subscription term, at least 1, defaulting to 12.

`allowed_frequency_weeks` is a non-empty array of positive integers enumerating the cadences a subscription on this plan may choose; omitted, it defaults to the three values 2, 4 and 8. `max_pause_cycles` bounds how many cycles any single pause may span, at least 1, defaulting to 3. `addon_catalog` is the array of purchasable extras, each entry a `code`, a `unit_price_cents` and a `unit_cogs_cents`, and it defaults to empty. `margin_floor_pct` is the guardrail: the minimum blended-term margin a save offer may leave behind, expressed as a four-decimal fraction from `0.0000` through `1.0000` inclusive. `downgrade_target_plan_id` names the plan that a plan-downgrade save offer moves subscriptions to; it defaults to null, and a null value makes downgrade offers structurally ineligible on this plan. `status` is either `ACTIVE` or `RETIRED` and defaults to `ACTIVE`; a retired plan may not take new subscriptions. `active_subscription_count` is maintained by the server rather than supplied: it is the number of subscriptions on this plan whose `lifecycle_state` is `ACTIVE`, `PAUSED` or `PENDING_CANCEL`, and it starts at 0.

Because `downgrade_target_plan_id` is a self-reference into the plan table, plans can be listed filtered by it, which yields the set of plans that downgrade into one given plan. Listing also filters on `status`, and pages with `limit` and `offset`.

**Save-offer templates** are the retention playbook, also authored by a `PlatformAdmin`. Each has a `code` unique across templates, a `name`, and an `offer_type` naming the lever it pulls: `PAUSE`, `SKIP`, `DISCOUNT` or `PLAN_DOWNGRADE`. Four fields parameterise the lever, and each is 0 or `0.0000` by default so that a template only carries the parameters its own type uses: `discount_pct` is the discount fraction (at least `0.0000`, strictly below `1.0000`, four decimals) and `discount_cycles` the number of cycles it runs for, both zero for non-discount types; `pause_cycles` is the number of cycles a pause offer pauses for, zero otherwise; and `skip_count` is the number of shipment units a skip offer skips, zero otherwise.

Eligibility is expressed by three template fields. `min_tenure_days` is the minimum subscriber tenure in days, with an inclusive boundary — a subscriber whose tenure exactly equals it qualifies — and it defaults to 0. `eligible_reason_codes` enumerates the cancellation reasons this template may be shown for and defaults to an empty array, which means the template matches no reason at all and will never be presented. `max_per_subscriber_per_365d` caps how many grants of this template one subscriber may receive inside a trailing window of 365 days, and defaults to 1. Finally, `priority_rank` is the primary ranking key of the offer selector — an integer of at least 1, where a *lower* rank is presented first — `expires_after_hours` is how long a presented offer stays acceptable, defaulting to 48 hours, and `status` is `ACTIVE` or `RETIRED` with `ACTIVE` the default. Only `ACTIVE` templates ever enter the candidate set.

### 3.2. Registration, Payment Instruments and Starting a Subscription

A `PlatformAdmin` registers a **Subscriber** with an `email` unique across subscribers and an `acquisition_channel`, one of `PAID_SOCIAL`, `SEARCH`, `AFFILIATE`, `ORGANIC` or `REFERRAL`. The channel drives cohort grouping and the projected churn rate of §3.9. A `do_not_contact` flag records the marketing opt-out and defaults to false; a subscriber or a `PlatformAdmin` may later flip it, which is the only field the marketing-preference update touches and which bumps the subscriber's `version`. At registration the derived fields start clean: `churn_type` is `NONE`, `realized_ltv_cents` and `projected_ltv_cents` are 0, and `save_offer_grants_365d_count` is 0.

A **payment method** is attached by the subscriber (or by a `PlatformAdmin` on their behalf) with a `subscriber_id`, a `card_last4` that must be exactly four digits, an `exp_month` between 1 and 12 inclusive, an `exp_year` of 2020 or later, and a `network` of `VISA`, `MASTERCARD`, `AMEX` or `DISCOVER`. Attaching a card is not an isolated act: the subscriber's previously `ACTIVE` method becomes `REPLACED`, and every subscription of that subscriber whose `lifecycle_state` is anything other than `CANCELLED` has its `payment_method_id` repointed at the new method, each such repoint incrementing that subscription's `version` by one. A method's `status` is `ACTIVE` while chargeable, `REPLACED` once a newer method superseded it, and `EXPIRED` once the card-updater network reported the card unavailable; it starts `ACTIVE`. Its `updater_status` tracks the card-updater service and takes the values `NONE` (the default), `PENDING`, `UPDATED` and `UNAVAILABLE`, with `updater_requested_at` recording the clock instant at which it became `PENDING` and staying null while it is `NONE`. Payment methods can be listed filtered by `subscriber_id` and `status`.

Starting a **Subscription** requires a `subscriber_id`, a `plan_id`, a `payment_method_id`, a `frequency_weeks` cadence, and a `disclosure_acknowledged` boolean recording that the subscriber saw the negative-option disclosure. An `addons` array may be supplied, and an optional `winback_target_id` cites the win-back target this signup converts. The guards run in this order after the ownership check of §2.6: the plan's `status` must be `ACTIVE` or the request is rejected with `ERR_PLAN_RETIRED` (422); when the plan is a negative-option plan, `disclosure_acknowledged` must be true or the request is rejected with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` (422); `frequency_weeks` must be a member of the plan's `allowed_frequency_weeks` or the request is rejected with `ERR_FREQUENCY_NOT_ALLOWED` (422); every supplied addon `code` must appear in the plan's `addon_catalog` or the request is rejected with `ERR_ADDON_NOT_AVAILABLE` (422); and the nominated payment method's `status` must be `ACTIVE` or the request is rejected with `ERR_PAYMENT_METHOD_INACTIVE` (409).

A successful signup does a great deal at once. `lifecycle_state` starts at `ACTIVE` and `billing_state` at `CURRENT`. The cycle length in days is `frequency_weeks` multiplied by seven, and both `next_renewal_at` and `next_ship_at` are set to the creation instant plus one cycle length. Each entry of `addons` is snapshotted from the plan's `addon_catalog` as a `code`, a `qty`, a `unit_price_cents` and a `unit_cogs_cents`, so later catalogue edits cannot silently reprice a live subscription; `addons` defaults to empty. `active_discount_pct` starts at `0.0000` and `discount_remaining_cycles` at 0. The shipment ledger is initialised with `term_shipments_delivered` at 1, `term_shipments_skipped` at 0 and `term_shipments_remaining` at the plan's `shipments_per_term` minus one. `committed_price_cents` is computed and copied into `baseline_price_cents`. `paused_until`, `cancel_effective_at`, `first_failed_at` and `grace_end_at` are all null, and `consecutive_failed_attempts` is 0. The plan's `active_subscription_count` increments. If this is the subscriber's first subscription, `first_subscribed_at` is set to the clock and `cohort_month` to that instant formatted as a four-digit year, a hyphen and a two-digit month in UTC; `first_subscribed_at` is never overwritten thereafter.

A signup on a negative-option plan also lays down its own paper trail: a `NEGATIVE_OPTION_DISCLOSURE` notice created already `SENT` with `sent_at` at the clock and `renewal_cycle_index` 0, and a `RENEWAL_REMINDER` notice created `SCHEDULED` with `scheduled_for` at `next_renewal_at` minus the plan's `renewal_reminder_days_before` and `renewal_cycle_index` 1.

The signup invoice is created immediately: an `Invoice` with `cycle_index` 0, `status` `OPEN` and `is_renewal` false, priced by the invoice arithmetic of §3.4 with the addon unit prices and unit COGS taken from the snapshot. When `winback_target_id` is supplied, the cited target moves to `CONVERTED` with `converted_at` at the clock, the subscriber's `churn_type` returns to `NONE`, `lapsed_at` is cleared to null, `won_back_at` is set to the clock, and the owning campaign's `converted_count` increments. A target may only convert from `SENT`, and the new subscription's `subscriber_id` must equal the target's `subscriber_id`.

Subscriptions can be listed filtered by `subscriber_id`, `plan_id`, `payment_method_id`, `lifecycle_state` and `billing_state`.

### 3.3. Subscriber-Initiated Change: Cadence, Addons, Skips, Pauses and Downgrades

A **modification** is how anything about a live subscription changes. Both a `Subscriber` and a `RetentionSpecialist` may request one, and every request carries a `mod_type` drawn from `FREQUENCY_CHANGE`, `ADDON_ADD`, `ADDON_REMOVE`, `SKIP_SHIPMENT`, `PLAN_DOWNGRADE`, `PAUSE`, `RESUME` and `DISCOUNT_APPLY`, plus the mandatory `expected_subscription_version` described in §2.7. Type-specific inputs travel alongside and are null when the type does not use them: `frequency_weeks` for a cadence change, `addon_code` for either addon operation, `addon_qty` (at least 1 when present) for an addon addition, `skip_ship_at` naming the cycle instant being skipped, `pause_start_at` and `pause_end_at` bounding a pause, and `target_plan_id` for a downgrade.

`effective_at` decides whether the change lands now or later. Omitted, it defaults to the logical clock, and the row settles immediately into `APPLIED`. A future `effective_at` settles the row into `SCHEDULED` instead. `REQUESTED` is the transient initial value that the create call always resolves; the full set of values is `REQUESTED`, `SCHEDULED`, `APPLIED`, `REVERSED` and `CANCELLED`, and `REVERSED` and `CANCELLED` are terminal.

The guards on a modification request run in this order once the version check of §2.7 has passed: the subscription's `lifecycle_state` must be `ACTIVE` or `PAUSED`, and a subscription in `PENDING_CANCEL` or `CANCELLED` is rejected with `ERR_SUBSCRIPTION_NOT_MODIFIABLE` (409); then the pause-overlap check; then `frequency_weeks` membership in `allowed_frequency_weeks` (`ERR_FREQUENCY_NOT_ALLOWED`, 422); then `addon_code` membership in the current plan's `addon_catalog` (`ERR_ADDON_NOT_AVAILABLE`, 422); then the pause-span check; then the skip-budget check; then the downgrade-target check.

A **pause** is bounded by a half-open window: the subscription is paused from `pause_start_at` inclusive up to `pause_end_at` exclusive. The requested window may not overlap the window of any existing pause modification whose `state` is `APPLIED` or `SCHEDULED`; because the semantics are half-open, a new window that starts exactly where a prior window ended is permitted, while any true overlap is rejected with `ERR_PAUSE_WINDOW_OVERLAP` (409). The span of the pause in cycles is the window's duration divided by the cycle length in days, rounded **up** to a whole number, and that figure may not exceed the plan's `max_pause_cycles`; a longer pause is rejected with `ERR_PAUSE_EXCEEDS_MAX_CYCLES` (422). An applied pause moves `lifecycle_state` from `ACTIVE` to `PAUSED`, sets `paused_until` to `pause_end_at`, advances `next_renewal_at` to `pause_end_at`, increases `pause_cycles_used` by the same rounded-up cycle count, and records `delta_price_cents` of 0 — a pause defers revenue but does not reprice the subscription. `pause_cycles_used` is the sum of pause cycles across every pause modification on the subscription whose `state` is `APPLIED` or `REVERSED`.

A **resume** moves `lifecycle_state` from `PAUSED` back to `ACTIVE`, clears `paused_until` to null, and — when it was requested as a modification rather than reached by the renewal run — sets `next_renewal_at` to the clock, so billing restarts immediately rather than at the originally deferred instant.

A **skip** consumes one unit of the shipment allotment. It requires `term_shipments_remaining` to be strictly greater than zero; a skip requested against an exhausted allotment is rejected with `ERR_SKIP_BUDGET_EXHAUSTED` (422). Applying it increments `term_shipments_skipped` and decrements `term_shipments_remaining`.

A **plan downgrade** requires that `target_plan_id` equal the current plan's `downgrade_target_plan_id` and that the latter not be null; anything else is rejected with `ERR_DOWNGRADE_TARGET_MISSING` (422). Applying it repoints `plan_id` at the target plan and drops from `addons` every entry whose `code` is absent from the target plan's `addon_catalog`. If the subscription has an `OPEN` invoice at that moment, that invoice is re-priced from the target plan under the mid-cycle repricing rules of §3.4, and a `PRICE_CHANGE` notice is created `SCHEDULED` with `scheduled_for` one day after the clock.

A **frequency change** replaces `frequency_weeks`, which changes the cycle length and therefore every subsequent renewal interval. An **addon addition** appends an entry snapshotted from the current plan's `addon_catalog` with the requested `addon_qty`; an **addon removal** drops the entry with the matching `addon_code`. A **discount application** sets `active_discount_pct` and `discount_remaining_cycles`; the discount applies to every line item while `discount_remaining_cycles` is greater than zero, and each renewal that issues an invoice decrements that counter.

Every application captures `prior_snapshot` immediately before touching the subscription. The snapshot holds exactly seven values — `plan_id`, `frequency_weeks`, `addons`, `active_discount_pct`, `discount_remaining_cycles`, `committed_price_cents` and `term_shipments_skipped` — and a reversal restores precisely those. `applied_at` records the clock instant of the transition into `APPLIED` and stays null while the row is `SCHEDULED` or `CANCELLED`. `delta_price_cents` is the subscription's `committed_price_cents` after application minus its value before, is 0 for rows that do not move price, and is 0 while the row is `SCHEDULED` or `CANCELLED`. A row that settles into `SCHEDULED` mutates nothing on the subscription except its `version`.

`committed_price_cents` is recomputed on every transition that moves `plan_id`, `addons`, `active_discount_pct` or `frequency_weeks` — a modification applied, a modification reversed, a save offer accepted, a save offer revoked. It is the plan component plus the addon components, each rounded separately: the plan component is `monthly_price_cents` multiplied by `shipments_per_cycle` multiplied by one minus `active_discount_pct`, rounded half up to whole cents; each addon component is that addon's `unit_price_cents` multiplied by its `qty` multiplied by one minus `active_discount_pct`, rounded half up to whole cents; the results are then added. The conservation invariant of §2.9 must hold after every such recomputation.

**Reversal** is a `RetentionSpecialist` (or `PlatformAdmin`) capability that takes an optional `reason_note`. It is only meaningful on a row whose `state` is `APPLIED` or `SCHEDULED`; a row in `REQUESTED`, `REVERSED` or `CANCELLED` is rejected with `ERR_MODIFICATION_NOT_REVERSIBLE` (409). Reversing a `SCHEDULED` row simply sets that row to `CANCELLED` and returns it, creating no compensating row, because nothing was ever applied. Reversing an `APPLIED` row moves it to `REVERSED` and creates a compensating modification whose `reverses_modification_id` names the original, whose own `state` is `APPLIED`, and whose `delta_price_cents` is the exact arithmetic inverse of the original's; every field captured in `prior_snapshot` is restored on the subscription. An `APPLIED` row may only be reversed while no later `APPLIED` modification on the same subscription references the fields its `prior_snapshot` captured. When the reversed row carries a `save_offer_grant_id`, the cascade continues: that grant moves from `ACCEPTED` to `REVOKED`, the subscriber's `winback_suppressed_until` is cleared to null when it was that grant which set it, `save_offer_grants_365d_count` is recomputed back to its pre-grant value, and `active_discount_pct` and `discount_remaining_cycles` are restored from the snapshot. Either flavour of reversal increments the subscription's `version`, and either flavour responds `200 OK` carrying the targeted modification row itself — the row just set to `CANCELLED`, or the original row now in `REVERSED` with its own `delta_price_cents` left intact — rather than the compensating row, even though the `APPLIED` branch does bring that compensating row into existence; the compensating row is reached through the `reverses_modification_id` list filter instead.

Modifications can be listed filtered by `subscription_id`, `save_offer_grant_id`, `reverses_modification_id`, `target_plan_id`, `state` and `mod_type`; `reverses_modification_id` and `save_offer_grant_id` are the reverse-reachability handles from an original row or a grant to what it produced.

### 3.4. Invoicing and the Renewal Run

An **Invoice** is the billable artifact of one cycle. It records the `subscription_id` it belongs to and a `payment_method_id` snapshotted from the subscription at creation, so that retries keep charging the instrument the invoice was issued against even if the subscription is later repointed. `cycle_index` is 0 for the signup invoice and increments by one for each renewal-issued invoice on the same subscription, and `is_renewal` is correspondingly false for `cycle_index` 0 and true for renewal-issued invoices. `status` starts `OPEN` and takes the values `OPEN`, `FAILED`, `PAID` and `WRITTEN_OFF`, with `PAID` and `WRITTEN_OFF` terminal. `due_at` is the clock instant of invoice creation; `paid_at` is the `attempted_at` of the successful charge attempt and is null while the invoice is unpaid; `attempt_count` counts the charge attempts recorded against this invoice and starts at 0. Invoices can be listed filtered by `subscription_id`, `payment_method_id` and `status`.

**Invoice arithmetic.** Let the cycle length in days be `frequency_weeks` multiplied by seven. The `proration_factor` is exactly `1.0000` for a freshly issued invoice. When an `OPEN` invoice is re-priced mid-cycle, it is instead the remaining days divided by the cycle length in days, rounded half up to four decimal places, where the remaining days is the difference between `next_renewal_at` and the clock expressed in days and rounded **down** to a whole number. The discount multiplier is one minus `active_discount_pct`, which is 1 whenever `discount_remaining_cycles` is 0.

The plan line is `monthly_price_cents` multiplied by `shipments_per_cycle`, multiplied by the discount multiplier, multiplied by the `proration_factor`, rounded half up to whole cents. Each addon line is that addon's `unit_price_cents` multiplied by its `qty`, multiplied by the discount multiplier, multiplied by the `proration_factor`, rounded half up to whole cents. `amount_cents` is the plan line plus the sum of the addon lines — each line rounded first, then summed, per the pinned ordering of §2.8.

`cogs_cents` is built the same way but **ignores the discount entirely**, because a discount does not make goods cheaper: it is `unit_cogs_cents` multiplied by `shipments_per_cycle` multiplied by the `proration_factor`, rounded half up to whole cents, plus, for each addon, that addon's `unit_cogs_cents` multiplied by its `qty` multiplied by the `proration_factor`, rounded half up to whole cents.

`line_items` records the breakdown in a pinned order — the plan line first, then one line per addon ordered by `code` ascending — and each entry carries a `kind`, a `code`, a `unit_price_cents`, a `qty` and a `line_cents`. The inputs to all of this are the subscription's current `plan_id`, `addons`, `frequency_weeks` and `active_discount_pct` (the latter contributing only while `discount_remaining_cycles` is greater than zero), all read **after** any modification applied within the same request.

Two variants of this arithmetic exist. For a freshly issued invoice — at signup or at renewal — the `proration_factor` is exactly `1.0000` and the lines reflect the plan as of issuance. For a mid-cycle repricing, triggered when an applied plan downgrade changes `plan_id` while an `OPEN` invoice exists, the `proration_factor` is below `1.0000`, the lines are rebuilt from the **target** plan, and addons absent from the target plan's `addon_catalog` are dropped before the lines are constructed.

**The renewal run** is a `BillingOperator` checkpoint over one subscription, and it is where every deferred obligation comes due. The run is refused before the cycle is up: if the clock has not yet reached `next_renewal_at`, the request is rejected with `ERR_RENEWAL_NOT_DUE` (409) and nothing is mutated. Otherwise the run executes seven steps in this fixed order.

Step one finalises a due cancellation. A subscription in `PENDING_CANCEL` whose `cancel_effective_at` the clock has reached moves to `CANCELLED`: no invoice is issued for the cycle, the subscriber's `churn_type` is set to `VOLUNTARY` and `lapsed_at` to the clock, and `projected_ltv_cents` is re-derived with zero expected remaining cycles so that it equals `realized_ltv_cents`. Steps five through seven are then skipped, which is why the negative-option reminder gate never applies to a subscription that is on its way out.

Step two auto-resumes a lapsed pause: a subscription in `PAUSED` whose `paused_until` the clock has reached moves to `ACTIVE` and `paused_until` is cleared to null.

Step three sweeps stale cancellation conversations: every `CancellationSession` on this subscription that is still non-terminal and was started more than 48 hours before the clock moves to `ABANDONED` with `completed_at` at the clock, and each of that session's `PRESENTED` grants moves to `EXPIRED`.

Step four applies deferred change: every modification on this subscription in `SCHEDULED` whose `effective_at` the clock has reached moves to `APPLIED`, processed in `created_at` ascending order across all due rows, after which the cycle is re-priced.

Step five is the negative-option gate. For a subscription on a negative-option plan, the run may only issue an invoice if a `ComplianceNotice` exists with `notice_type` `RENEWAL_REMINDER`, `state` `SENT`, and `renewal_cycle_index` equal to the cycle being renewed, whose `sent_at` falls inside the closed reminder window described in §2.11. If no such notice exists, the run is rejected with `ERR_RENEWAL_REMINDER_MISSING` (422) and **nothing at all is mutated**.

Step six records the compliance gap: every `ComplianceNotice` on this subscription still in `SCHEDULED` whose `scheduled_for` is earlier than the clock moves to `MISSED`. That records the omission without blocking renewals of plans that are not negative-option.

Step seven bills the cycle, and there are two outcomes. If an `APPLIED` skip modification carries a `skip_ship_at` equal to the subscription's `next_ship_at`, the cycle is skipped: no invoice is issued and only `next_renewal_at` and `next_ship_at` advance, each by one cycle length in days. Otherwise the payment instrument must still be usable — a subscription whose `payment_method_id` points at a method whose `status` is `REPLACED` or `EXPIRED` is rejected with `ERR_PAYMENT_METHOD_INACTIVE` (409), because a stale card may be retried against an invoice that already exists but may never have a new invoice issued against it — and then a new `Invoice` is created with `cycle_index` one greater than the previous invoice's, `status` `OPEN` and `is_renewal` true. `term_shipments_delivered` increments and `term_shipments_remaining` decrements, `discount_remaining_cycles` decrements when it is above zero, `next_renewal_at` and `next_ship_at` each advance by one cycle length in days, and, on a negative-option plan, a fresh `RENEWAL_REMINDER` notice is scheduled for the following cycle. `next_ship_at` normally equals `next_renewal_at`; it runs one further cycle length ahead whenever the cycle in between was skipped.

The run also finalises a `PENDING_CANCEL` subscription only when the clock has reached `cancel_effective_at`; the lifecycle move from `PENDING_CANCEL` to `CANCELLED` is never performed by any subscriber-facing operation. Every renewal run that changes anything increments the subscription's `version` by one.

Statutory notices can be scheduled outside the automatic flow by a `BillingOperator` or a `ComplianceOfficer`, supplying a `notice_type`, a `scheduled_for` instant and optionally a `channel` and a `body_ref`; the server fills in `renewal_cycle_index` from the `cycle_index` of the upcoming renewal. When the notice type is `RENEWAL_REMINDER`, the supplied `scheduled_for` must itself lie inside the closed reminder window, and an instant outside it is rejected with `ERR_NOTICE_WINDOW_INVALID` (422). Sending a notice is a `BillingOperator` capability whose guards run in this order: the notice's `state` must be `SCHEDULED`, and a notice already `SENT` or `MISSED` is rejected with `ERR_NOTICE_ALREADY_SENT` (409); then the three-day cooldown of §2.11, whose violation is `ERR_NOTICE_COOLDOWN_ACTIVE` (409); then, for a `RENEWAL_REMINDER`, the clock itself must lie inside the closed reminder window, and a send outside it is rejected with `ERR_NOTICE_WINDOW_INVALID` (422). A successful send moves the notice to `SENT` with `sent_at` at the clock and increments its `version`. A subscription's notices can be read back filtered by `notice_type` and `state`.

### 3.5. The Cancellation Conversation

A **CancellationSession** is the recorded conversation between a subscriber who wants out and the retention flow that gets one chance to change their mind. It is opened by a `Subscriber` or a `RetentionSpecialist` against a `subscription_id`, declaring the `entry_channel` the subscriber came from: `WEB_SELF_SERVE`, `APP_SELF_SERVE` or `AGENT_ASSISTED`. Two guards apply in order: the subscription's `lifecycle_state` must be `ACTIVE` or `PAUSED`, otherwise `ERR_SUBSCRIPTION_NOT_MODIFIABLE` (409); and no other session on the same subscription may be in `STARTED`, `REASON_CAPTURED` or `OFFERS_PRESENTED`, otherwise `ERR_SESSION_ALREADY_OPEN` (409). A new session records `state` `STARTED`, `step_count` 1, `offers_presented_count` 0, and `started_at` at the clock, with `reason_code`, `reason_detail`, `completed_at` and `presented_by_user_id` all null.

The session's `state` takes six values: `STARTED`, `REASON_CAPTURED`, `OFFERS_PRESENTED`, `OFFER_ACCEPTED`, `COMPLETED_CANCELLED` and `ABANDONED`. The last three are terminal. `completed_at` records the clock instant of the move into `COMPLETED_CANCELLED`, `OFFER_ACCEPTED` or `ABANDONED`, and is null while the session is non-terminal. Any state-advancing call against a session already in one of the three terminal states is rejected with `ERR_SESSION_ALREADY_TERMINAL` (409), and that check is the first domain guard on reason capture, offer presentation and completion alike.

**The step budget is the mechanism behind the simple-cancellation guarantee.** `step_count` counts the state-advancing calls recorded on the session and starts at 1 for the create call. A subscriber must always be able to finish in at most four recorded steps, of which the completion call is the last; pre-completion calls therefore share a budget of three. Concretely, a pre-completion call is permitted only when the session's current `step_count` plus one is less than or equal to three — the boundary is inclusive, so `step_count` may legitimately reach 3 — and a call that would push it past three is rejected with `ERR_SIMPLE_CANCELLATION_VIOLATION` (422) with no state change of any kind. Reason capture and offer presentation each consume one step. Completion also increments `step_count`, but is **exempt** from the check: the guarantee is that finishing is always reachable.

**Reason capture** moves the session from `STARTED` to `REASON_CAPTURED`, setting `reason_code` to one of `PRICE`, `PRODUCT_FIT`, `TOO_MUCH_PRODUCT`, `SHIPPING_ISSUES`, `FINANCIAL_HARDSHIP` or `OTHER`, together with an optional free-text `reason_detail`, and incrementing `step_count`. The same call may be repeated on a session already in `REASON_CAPTURED` as a **revision**: the state stays `REASON_CAPTURED`, `reason_code` and `reason_detail` are overwritten, and `step_count` increments again. A revision is not free — it consumes one of the three pre-completion steps, and a subscriber who revises twice can starve the offer round entirely. The guards on reason capture run in this order: session not terminal (`ERR_SESSION_ALREADY_TERMINAL`), then the step budget (`ERR_SIMPLE_CANCELLATION_VIOLATION`).

**Completion** takes a `confirm` input and drives the session from either `REASON_CAPTURED` or `OFFERS_PRESENTED` into `COMPLETED_CANCELLED`, setting `completed_at` to the clock and incrementing `step_count`. Its guards are, in order: session not terminal (`ERR_SESSION_ALREADY_TERMINAL`, 409), then `reason_code` must not be null (`ERR_REASON_NOT_CAPTURED`, 409) — a subscriber cannot complete a cancellation whose reason was never captured. Completion has identical consequences from either origin state: the subscription moves from `ACTIVE` or `PAUSED` to `PENDING_CANCEL` with `cancel_effective_at` set to `next_renewal_at`, and the subscription's `version` increments. Every `SaveOfferGrant` on the session still in `PRESENTED` moves to `EXPIRED`, which recomputes the subscriber's `save_offer_grants_365d_count`. A `CANCELLATION_CONFIRMATION` notice is created already `SENT` with `sent_at` at the clock. Note what completion does **not** do: it does not end access. Access continues through the paid term, and the lifecycle move from `PENDING_CANCEL` to `CANCELLED` is executed later by the renewal run of §3.4 once the clock reaches `cancel_effective_at`.

A session can also end without the subscriber saying anything more. When the renewal run finds a non-terminal session older than 48 hours it moves it to `ABANDONED` with `completed_at` at the clock, expiring its `PRESENTED` grants; the same happens when the subscription reaches `CANCELLED` involuntarily. Abandonment deliberately **preserves** `reason_code`, because the win-back scoring of §3.8 still reads it long afterwards. Sessions can be listed filtered by `subscription_id` and `state`.

### 3.6. Save Offers: Selection, Margin Guardrails and the Exception Desk

An **offer-presentation round** is exclusive to a `RetentionSpecialist`, may run at most once per session, and produces exactly one `SaveOfferGrant`. It moves the session from `REASON_CAPTURED` to `OFFERS_PRESENTED`, sets the session's `presented_by_user_id` to the acting `X-User-ID`, sets `offers_presented_count` to 1 and increments `step_count`. Its guards run in this order: session not terminal (`ERR_SESSION_ALREADY_TERMINAL`, 409); `reason_code` not null (`ERR_REASON_NOT_CAPTURED`, 409); the step budget together with the requirement that `offers_presented_count` still be 0, a second round being rejected with `ERR_SIMPLE_CANCELLATION_VIOLATION` (422); then the tenure rule, then the quota rule, then the eligibility rule described below.

**The eligibility filter.** A save-offer template is a candidate for this session when all of the following hold: its `status` is `ACTIVE`; the session's `reason_code` is a member of the template's `eligible_reason_codes`; the subscriber's `tenure_days` is greater than or equal to the template's `min_tenure_days`; if the template's `offer_type` is `PAUSE`, the subscription's `lifecycle_state` is `ACTIVE`; if the `offer_type` is `SKIP`, the subscription's `term_shipments_remaining` is greater than zero; and if the `offer_type` is `PLAN_DOWNGRADE`, the current plan's `downgrade_target_plan_id` is not null.

The trailing-365-day grant quota is deliberately **not** part of that filter. The selector never skips a quota-exhausted template, so an exhausted top-ranked offer still wins the ranking and is then rejected by the quota rule. Filtering it out here instead would make that rejection unreachable and would silently promote a cheaper offer that the retention policy never authorised.

**The ranking.** Candidates are ordered by `priority_rank` ascending; where those tie, by `blended_term_margin_pct` descending; and where both tie, by `created_at` ascending. The first row of that ordering is selected, and its `id` becomes the grant's `save_offer_template_id`.

**The three rejections, in priority order.** First, if every `ACTIVE` template whose `eligible_reason_codes` contains the session's `reason_code` was excluded *solely* because the subscriber's `tenure_days` fell below `min_tenure_days`, the round is rejected with `ERR_TENURE_REQUIREMENT_NOT_MET` (422) — and in that case the empty-pool rejection below does not fire. Second, if the grants of the *selected* template for this subscriber inside the trailing 365 days have already reached that template's `max_per_subscriber_per_365d`, the round is rejected with `ERR_OFFER_QUOTA_EXCEEDED` (422); the count must be strictly below the cap for the round to proceed. Third, if the eligibility filter yields no candidate for any reason other than tenure — no template lists the `reason_code` at all, the `offer_type`'s structural precondition fails, or every match is `RETIRED` — the round is rejected with `ERR_NO_ELIGIBLE_SAVE_OFFER` (422). All three rejections leave the session exactly as it was: `state` stays `REASON_CAPTURED`, and `offers_presented_count` and `step_count` are unchanged, so the subscriber can still complete within the simple-cancellation budget.

**Margin arithmetic.** Every grant is created with two margin readings, and confusing them is the single most expensive mistake available here. Let the current plan's `monthly_price_cents` be the cycle list price, its `unit_cogs_cents` the per-shipment cost, and `shipments_per_cycle` the shipments per cycle. The horizon beyond the offer is fixed at **three** post-offer cycles.

The offer window's shape depends on `offer_type`. For a `DISCOUNT` offer, the number of offer cycles is `discount_cycles`; each offer cycle's revenue is the cycle list price multiplied by `shipments_per_cycle` multiplied by one minus `discount_pct`, rounded half up to whole cents, and each offer cycle's cost of goods is `unit_cogs_cents` multiplied by `shipments_per_cycle`. For a `PAUSE` offer, the number of offer cycles is `pause_cycles`, and both revenue and cost of goods per offer cycle are zero. For a `SKIP` offer, the number of offer cycles is `skip_count`, and again both are zero. For a `PLAN_DOWNGRADE` offer there is **no** offer cycle at all — the number of offer cycles is zero — and the entire horizon is priced on the target plan instead.

Each of the three post-offer cycles is priced on the **current** plan at list: revenue is `monthly_price_cents` multiplied by `shipments_per_cycle`, rounded half up to whole cents, and cost of goods is `unit_cogs_cents` multiplied by `shipments_per_cycle`. The sole exception is `PLAN_DOWNGRADE`, whose post-offer cycles are priced on the target plan: revenue is the target plan's `monthly_price_cents` multiplied by `shipments_per_cycle`, rounded half up to whole cents, and cost of goods is the target plan's `unit_cogs_cents` multiplied by `shipments_per_cycle`.

The term totals follow. Total term revenue is the number of offer cycles multiplied by the offer-cycle revenue, plus three multiplied by the post-offer-cycle revenue. Total term cost of goods is the number of offer cycles multiplied by the offer-cycle cost of goods, plus three multiplied by the post-offer-cycle cost of goods. `retention_value_cents` — the contribution margin the offer retains over the horizon — is total term revenue minus total term cost of goods.

`per_cycle_margin_pct` is the display margin of the first offer cycle: the offer-cycle revenue minus the offer-cycle cost of goods, divided by the offer-cycle revenue, rounded half up to four decimal places, and exactly `0.0000` when the offer-cycle revenue is zero. For a `PLAN_DOWNGRADE`, which has no distinct offer cycle, this reading takes the **first post-offer cycle** instead, substituting the post-offer revenue and post-offer cost of goods into the same expression. This is the figure shown to the subscriber, and it is deliberately pessimistic: a deep short discount looks unprofitable when read one cycle at a time.

`blended_term_margin_pct` is the guardrail margin: total term revenue minus total term cost of goods, divided by total term revenue, rounded half up to four decimal places, and exactly `0.0000` when total term revenue is zero. Because it amortises the offer over the offer cycles *plus* the three post-offer cycles, the same offer reads considerably healthier here than in the per-cycle view, and an offer that would breach the floor on the per-cycle reading can clear it comfortably on the blended one.

**The guardrail uses `blended_term_margin_pct` and never `per_cycle_margin_pct`.** `margin_exception_required` is true exactly when `blended_term_margin_pct` is **strictly less than** the `margin_floor_pct` of the subscription's current plan; a blended margin exactly equal to the floor does not require an exception.

**The exception axis.** A grant carries a second, independent state machine in `margin_exception_state`, whose values are `NOT_REQUIRED`, `PENDING`, `APPROVED` and `REJECTED`. At creation it is `NOT_REQUIRED` unless `margin_exception_required` came out true, in which case the grant is created directly in `PENDING`. A `ComplianceOfficer` — and only a `ComplianceOfficer` — decides it by supplying a `decision` of either `APPROVE`, which moves the axis to `APPROVED`, or `REJECT`, which moves it to `REJECTED`, together with an optional `justification`. The decision records `decided_by_user_id` from the acting `X-User-ID` and increments the grant's `version`; `decided_by_user_id` is null while undecided. Its guards run in this order: the segregation-of-duties comparison of §2.1, whose violation is `ERR_SEGREGATION_OF_DUTIES` (403); then `margin_exception_state` must be `PENDING`, a decision on any other value being rejected with `ERR_MARGIN_EXCEPTION_NOT_REQUIRED` (409).

**The grant lifecycle.** A `SaveOfferGrant` records the `cancellation_session_id` it belongs to, the `save_offer_template_id` the selector chose, and a `subscription_id` copied from the session. Its `presented_by_user_id` is the presenting specialist's `X-User-ID` — the comparand for segregation of duties. Its `expires_at` is its `created_at` plus the template's `expires_after_hours` hours. Its `state` starts at `PRESENTED` and takes the values `PRESENTED`, `ACCEPTED`, `DECLINED`, `EXPIRED` and `REVOKED`, of which `DECLINED`, `EXPIRED` and `REVOKED` are terminal. `accepted_at` records the clock instant of acceptance and is null unless the state is `ACCEPTED`. Grants can be listed filtered by `cancellation_session_id`, `save_offer_template_id`, `subscription_id` and `state`.

**Accepting** an offer is exclusive to the `Subscriber`. Its guards run in this order after the ownership check: the grant's `state` must be `PRESENTED`, otherwise `ERR_OFFER_ALREADY_RESOLVED` (409); the clock must be strictly before `expires_at`, an acceptance at or after that instant being rejected with `ERR_OFFER_EXPIRED` (409); when the offer's `offer_type` is `DISCOUNT` or `PLAN_DOWNGRADE`, the subscription's `billing_state` must be `CURRENT`, otherwise `ERR_SUBSCRIPTION_PAST_DUE` (409) — we do not hand a discount to an account we are still trying to collect from; and finally either `margin_exception_required` must be false or `margin_exception_state` must be `APPROVED`, otherwise `ERR_MARGIN_FLOOR_BREACH` (422). A rejected exception therefore leaves the grant permanently unacceptable, failing with that same code.

Acceptance cascades in four directions. The grant moves to `ACCEPTED` with `accepted_at` at the clock. A `SubscriptionModification` implementing the offer's lever is created directly in `APPLIED` and mutates the subscription, with its `save_offer_grant_id` naming this grant; a `PLAN_DOWNGRADE` acceptance additionally re-prices the subscription's `OPEN` invoice from the target plan under the mid-cycle repricing variant and schedules a `PRICE_CHANGE` notice. The subscriber's `winback_suppressed_until` is set to the clock plus 90 days, so a subscriber we just saved is not immediately marketed to. The session moves to `OFFER_ACCEPTED` with `completed_at` at the clock and `step_count` incremented, while the subscription's `lifecycle_state` is left exactly as it was — the save succeeded, so there was never a cancellation to reverse. The subscription's `version` increments.

**Declining** is the divergent branch, and it is deliberately much lighter. It is also exclusive to the `Subscriber`, takes an optional `decline_note`, and is guarded by the same `state` check yielding `ERR_OFFER_ALREADY_RESOLVED` (409). The grant moves to `DECLINED` and the subscriber's `save_offer_grants_365d_count` is recomputed, since a declined grant leaves the trailing window. Unlike acceptance, no `SubscriptionModification` is created, no suppression window is set, and the session stays in `OFFERS_PRESENTED` so the subscriber can still complete the cancellation. `save_offer_grants_365d_count` itself is the number of grants belonging to any subscription of this subscriber whose `state` is `PRESENTED` or `ACCEPTED` and whose `created_at` falls on or after 365 days before the clock.

A grant reaches `EXPIRED` from `PRESENTED` when the session completes as a cancellation or is abandoned by the renewal run, and reaching `EXPIRED` likewise recomputes `save_offer_grants_365d_count`. A grant reaches `REVOKED` from `ACCEPTED` only when the modification it created is reversed, as described in §3.3.

### 3.7. Collections: Dunning, Card Updater and Involuntary Churn

Collections runs entirely on the billing axis and never asks the subscriber's permission. A **DunningAttempt** records one charge attempt against one `invoice_id`. `attempt_number` is the invoice's `attempt_count` plus one as observed at creation, so attempt 1 is the initial charge. `previous_attempt_id` names the immediately preceding attempt on the same invoice ordered by `created_at` ascending, and is null on the first attempt. `outcome` starts at `PENDING` and takes the values `PENDING`, `SUCCEEDED`, `SOFT_DECLINE` and `HARD_DECLINE`; `decline_code` is null unless the outcome is one of the two declines, and otherwise takes one of `INSUFFICIENT_FUNDS`, `EXPIRED_CARD`, `DO_NOT_HONOR` or `LOST_STOLEN`. `attempted_at` is the clock instant of settlement and is null while the outcome is `PENDING`. Attempts can be listed filtered by `invoice_id`, `outcome`, and `previous_attempt_id`, the last of which walks forward from one attempt to its successor.

**Scheduling an attempt** is a `BillingOperator` capability whose guards run in this order: the invoice's `status` must be `OPEN` or `FAILED`, and a `PAID` or `WRITTEN_OFF` invoice is rejected with `ERR_INVOICE_NOT_PAYABLE` (409); then, for any attempt after the first, the grace window must still be open; then the retry ceiling. Each accepted attempt increments the invoice's `attempt_count` and `version` and links `previous_attempt_id`.

The scheduling arithmetic is best read as an ordered procedure, because the dependency between the grace window and the retry schedule looks circular — the grace window bounds the retry schedule, while the card-updater state that widens the grace window is itself set by the decline that triggered the retry. The order below is normative, and each step reads only values written by earlier steps.

First, the base grace allowance is drawn from the subscriber's `tenure_bucket` **as evaluated at the subscription's `first_failed_at`**, not as of now: three days for `M0_1`, five for `M2_3`, seven for `M4_6`, ten for `M7_12`, and fourteen for `M13_PLUS`. Second, four further days are added to that allowance when — and only when — the invoice's payment method has `updater_status` `PENDING` as observed at this moment, before this attempt settles; otherwise nothing is added. Third, the subscription's `grace_end_at` is set to `first_failed_at` plus that total allowance in days. This recomputation happens on **every** attempt creation, which means an `UNAVAILABLE` card-updater result shrinks the window back to the bare tenure allowance.

Fourth, the raw schedule instant is the previous attempt's `attempted_at` plus a backoff in days chosen by that previous attempt's `decline_code`. The backoff lists, read as ordered positions, are: `INSUFFICIENT_FUNDS` one, three, five, then seven days; `EXPIRED_CARD` zero, two, four, then six days; `DO_NOT_HONOR` two, four, six, then eight days; and `LOST_STOLEN` zero days at every position. The position used is the one whose ordinal equals the previous attempt's `attempt_number` — so the attempt numbered 2 uses the first position of the list, the attempt numbered 3 the second, and the attempt numbered 4 the third. The chosen figure is stored on the new attempt as `backoff_days_applied`.

Fifth, `scheduled_at` is the **earlier** of the raw schedule instant and the subscription's `grace_end_at`. Sixth, `grace_clamped` is true exactly when the raw schedule instant fell **strictly after** `grace_end_at`, and `is_final` is set to the same value: a clamped attempt is the last one this invoice will get.

The very first attempt is special and skips all of that. For `attempt_number` 1 the raw schedule instant is simply the clock, `backoff_days_applied` is 0, `grace_clamped` is false and `is_final` is false, and the grace-window steps are skipped entirely because `first_failed_at` is still null.

Two rejections guard the schedule. A retry requested for `attempt_number` 2 or higher when the clock has passed the `grace_end_at` just recomputed is rejected with `ERR_GRACE_PERIOD_ENDED` (409). An attempt that would carry an `attempt_number` above four — the retry ceiling — is rejected with `ERR_DUNNING_ATTEMPTS_EXHAUSTED` (422).

**Settling an attempt** is done through a test-driving capability available to a `BillingOperator` or `PlatformAdmin`, which stands in for the external payment webhook: it supplies an `invoice_id`, an `outcome` and an optional `decline_code`, and writes them onto the invoice's `PENDING` attempt together with `attempted_at`. Its guards run in this order: the invoice's `status` must be `OPEN` or `FAILED` (`ERR_INVOICE_NOT_PAYABLE`, 409), then an attempt with `outcome` `PENDING` must actually exist on the invoice (`ERR_NO_PENDING_ATTEMPT`, 409).

A `SUCCEEDED` settlement moves the invoice from `OPEN` or `FAILED` to `PAID` with `paid_at` at the clock, drives `billing_state` from `PAST_DUE` or `GRACE` back to `CURRENT`, clears `first_failed_at` and `grace_end_at` to null, resets `consecutive_failed_attempts` to 0, and recomputes both of the subscriber's lifetime-value figures.

A `SOFT_DECLINE` on an attempt whose `is_final` is false moves the invoice from `OPEN` or `FAILED` to `FAILED` and drives `billing_state` from `CURRENT` to `PAST_DUE`. `consecutive_failed_attempts` — the count of declined attempts on the currently unpaid invoice — increments, and is reset to 0 whenever an invoice reaches `PAID`. On the first decline of this invoice, `first_failed_at` is set to the clock; it holds the `attempted_at` of the earliest declined attempt on the currently unpaid invoice and is cleared when that invoice reaches `PAID`. At this moment `grace_end_at` is set to `first_failed_at` plus the bare tenure allowance with **no** card-updater extension: the extension is applied only at the *next* attempt creation, by the second step of the procedure above. Note that this axis is genuinely independent — a `PAUSED` subscription can sit in `PAUSED` alongside `PAST_DUE`, and the lifecycle axis is untouched.

Any decline, soft or hard, carrying `decline_code` `EXPIRED_CARD` also asks the card-updater network for help: the invoice's payment method has `updater_status` set to `PENDING` and `updater_requested_at` set to the clock. That is what widens the grace window on the next attempt creation, and it is also what drives `billing_state` from `PAST_DUE` to `GRACE` at that next attempt creation — the transition into `GRACE` happens precisely because the extension applies.

The **card-updater result** is ingested by a `BillingOperator` for a method whose `updater_status` is `PENDING`; ingesting a result for any other value is rejected with `ERR_UPDATER_NOT_PENDING` (409). The call supplies an `outcome` and, optionally, replacement card details as `new_card_last4`, `new_exp_month` and `new_exp_year`. An `UPDATED` outcome sets `updater_status` to `UPDATED`, applies whichever of the replacement fields were supplied to `card_last4`, `exp_month` and `exp_year`, and keeps `status` `ACTIVE`. An `UNAVAILABLE` outcome sets `updater_status` to `UNAVAILABLE` and `status` to `EXPIRED`. Either way the method's `version` increments.

**Write-off is where involuntary churn is created.** A `HARD_DECLINE`, or a `SOFT_DECLINE` on an attempt whose `is_final` is true, moves the invoice from `OPEN` or `FAILED` to `WRITTEN_OFF`, and the consequences ripple outward in a fixed sequence. The invoice reaching `WRITTEN_OFF` drives `billing_state` from `PAST_DUE` or `GRACE` to `DELINQUENT`; that in turn drives `lifecycle_state` from `ACTIVE` or `PAUSED` to `CANCELLED` with `cancel_effective_at` set to the clock — note that involuntary cancellation is immediate, unlike voluntary cancellation, which honours the paid term. The subscriber's `churn_type` is set to `INVOLUNTARY`, `lapsed_at` to the clock, and `winback_suppressed_until` to the clock plus 30 days. `realized_ltv_cents` is recomputed, subtracting this invoice's `cogs_cents`, and `projected_ltv_cents` is re-derived with zero expected remaining cycles so that it equals `realized_ltv_cents`. Finally, every non-terminal `CancellationSession` on this subscription moves to `ABANDONED`. The subscription's `version` increments. The cascade is identical whether the lifecycle axis started in `ACTIVE` or `PAUSED`.

That last detail is the mechanical basis for separating churn types. `churn_type` takes `NONE`, `VOLUNTARY` or `INVOLUNTARY` and defaults to `NONE`. It becomes `VOLUNTARY` when the terminal cancellation came from a cancellation-session completion finalised by the renewal run, and `INVOLUNTARY` when it came from an invoice write-off. `lapsed_at` is the clock instant at which the subscriber's last non-cancelled subscription reached `CANCELLED`, and stays null while any subscription of theirs is still not `CANCELLED`.

### 3.8. Win-Back: Campaigns, Targeting and Suppression

A **WinBackCampaign** is created in `DRAFT` by a `RetentionSpecialist` with a `code` unique across campaigns, a `name`, an inclusive lower bound `min_days_since_lapse` of zero or more days, an inclusive upper bound `max_days_since_lapse` that must be at least `min_days_since_lapse`, and an `offer_discount_pct` at least `0.0000` and strictly below `1.0000` at four decimals. Optional scoping fields default to empty arrays that mean "no restriction": `target_channels` names the `acquisition_channel` values in scope, and an empty array puts every channel in scope; `target_reason_codes` names the latest-cancellation reason codes in scope, and an empty array puts every reason in scope. `send_window_days` is how long a sent target stays live before it may be expired, defaulting to 14, and `suppression_days` is how long after a send the same subscriber may not be re-targeted by this campaign, defaulting to 60. `state` runs `DRAFT`, `LAUNCHED`, `CLOSED`, with `CLOSED` terminal. Three counters are server-maintained and start at 0: `targeted_count` is the number of targets on this campaign, `sent_count` the number whose `state` is `SENT`, `EXPIRED` or `CONVERTED`, and `converted_count` the number in `CONVERTED`.

Launching moves a campaign from `DRAFT` to `LAUNCHED` and increments its `version`. A campaign already `LAUNCHED` may not be launched again. Closure is not a client action: a `LAUNCHED` campaign whose `targeted_count` is above zero and every one of whose targets is in `CONVERTED`, `EXPIRED` or `SUPPRESSED` is moved to `CLOSED`, and that evaluation is performed at the end of every target re-evaluation call.

**Targeting** adds one lapsed subscriber to a launched campaign, supplying a `subscriber_id` and the `expected_campaign_version` of §2.7. Its guards run in this order: the stale-version check (`ERR_STALE_CAMPAIGN_VERSION`, 412); then the campaign's `state` must be `LAUNCHED`, a `DRAFT` or `CLOSED` campaign being rejected with `ERR_CAMPAIGN_NOT_LAUNCHED` (409); then the subscriber's `lapsed_at` must not be null and the days since lapse must fall between `min_days_since_lapse` and `max_days_since_lapse` inclusive on both ends, otherwise `ERR_SUBSCRIBER_NOT_LAPSED` (422); then the subscriber's `winback_suppressed_until` must be null or at or before the clock, a later instant being rejected with `ERR_WINBACK_SUPPRESSION_ACTIVE` (422); then no target may already exist for this `winback_campaign_id` and `subscriber_id` pair, a duplicate being rejected with `ERR_DUPLICATE_TARGET` (409). A successful call increments both `targeted_count` and the campaign's `version`.

The new **WinBackTarget** records `days_since_lapse_at_target`, the difference between the clock and `lapsed_at` in days rounded down to a whole number, and snapshots the subscriber's `projected_ltv_cents` at the moment of targeting. Its `state` runs the cycle `ELIGIBLE` → `SENT` → `EXPIRED` → `ELIGIBLE`, and the complete value set is `ELIGIBLE`, `SUPPRESSED`, `SENT`, `EXPIRED` and `CONVERTED`, of which only `CONVERTED` is terminal. `sent_at` is the clock instant of the send and is null while never sent; `expires_at` is `sent_at` plus the campaign's `send_window_days` days and is likewise null while never sent; `converted_at` is the clock instant of the subscription creation that cited this target, and is null otherwise. Targets can be listed filtered by `winback_campaign_id`, `subscriber_id` and `state`.

**Suppression predicates are evaluated in a pinned order, and the first match wins**, setting `suppression_reason` to that predicate's name and putting the target in `SUPPRESSED`. The order is: first `DO_NOT_CONTACT`, when the subscriber's `do_not_contact` flag is true; second `ACTIVE_SUBSCRIPTION`, when the subscriber still holds a subscription whose `lifecycle_state` is `ACTIVE`, `PAUSED` or `PENDING_CANCEL`; third `INVOLUNTARY_UNRESOLVED`, when the subscriber's `churn_type` is `INVOLUNTARY` and the payment method of their most recently created subscription either has a `status` other than `ACTIVE` or has an `updater_status` of `PENDING` or `UNAVAILABLE`; fourth `RECENT_SAVE_OFFER`, when the subscriber has a grant in `ACCEPTED` whose `accepted_at` is on or after 90 days before the clock; and fifth `CONTACT_CAP`, when the subscriber's `last_contacted_at` is not null and is later than 30 days before the clock. When no predicate matches, the target is `ELIGIBLE` and `suppression_reason` is `NONE`, which is also its default. These predicates are evaluated both at target creation and at every re-evaluation.

**Sending** a win-back offer requires the campaign to be `LAUNCHED` (`ERR_CAMPAIGN_NOT_LAUNCHED`, 409), then the target's `state` to be `ELIGIBLE`, any other value being rejected with `ERR_TARGET_SUPPRESSED` (409), and then the contact cap: the number of this subscriber's targets whose `sent_at` lies inside the closed sliding window from 30 days before the clock up to the clock must be strictly below one. This is an aggregate capacity check, not a pairwise-overlap check, and exceeding it is rejected with `ERR_CONTACT_CAP_EXCEEDED` (422). In practice, therefore, one marketing contact per subscriber per 30 days is the ceiling. A successful send moves the target from `ELIGIBLE` to `SENT`, sets `sent_at` to the clock and `expires_at` to the clock plus the campaign's `send_window_days` days, sets the subscriber's `last_contacted_at` to the clock, and increments the campaign's `sent_count`. `last_contacted_at` is defined as the `sent_at` of the most recent target for this subscriber whose `state` is `SENT`, `EXPIRED` or `CONVERTED`, ordered by `sent_at` descending and then `created_at` descending, and is null when the subscriber was never contacted.

**Re-evaluation** re-runs the target state machine against the clock and the suppression predicates, applying exactly one transition per call, and returns 200 with the target unchanged when no declared transition's preconditions hold. A target in `SENT` whose `expires_at` the clock has reached moves to `EXPIRED`, and `sent_at` is deliberately left intact so that the contact cap keeps counting it. A target in `EXPIRED` moves back to `ELIGIBLE` when the clock has reached `sent_at` plus the campaign's `suppression_days` days and no suppression predicate holds; `expires_at` is cleared to null and `suppression_reason` set to `NONE`, closing the cycle so the target may be sent again. A target in `SUPPRESSED` moves to `ELIGIBLE` when no suppression predicate holds any more, with `suppression_reason` set to `NONE`. A target in `ELIGIBLE` moves to `SUPPRESSED` when at least one predicate holds. And at the end of every re-evaluation call, the campaign closure condition above is checked.

**The priority score** is computed once, at target creation, and stored as `priority_score`. It is the round-half-up to four decimal places of the sum of three weighted terms. The first term is 0.45 multiplied by the lesser of 1 and the subscriber's `realized_ltv_cents` divided by 20000 — twenty thousand cents, two hundred dollars, being the normaliser at which a lapsed subscriber counts as maximally valuable. That "lesser of" clamps only at the upper bound: a negative `realized_ltv_cents` contributes a negative first term unchanged. The second term is 0.30 multiplied by one minus the lesser of 1 and the days since lapse divided by the greater of 1 and the campaign's `max_days_since_lapse`, so a recently lapsed subscriber scores higher and the campaign's own upper bound doubles as the recency normaliser. The third term is 0.25 multiplied by a weight drawn from the reason code: `PRICE` weighs 1.0, `TOO_MUCH_PRODUCT` 0.8, `FINANCIAL_HARDSHIP` 0.7, `SHIPPING_ISSUES` 0.6, `PRODUCT_FIT` 0.4 and `OTHER` 0.2, with 0.0 used when there is no reason code at all. The reason code for this purpose is the `reason_code` of the most recent `CancellationSession` on any subscription of this subscriber, ordered by `started_at` descending and then `created_at` descending, **in any state whatsoever** — which is exactly why abandonment preserves the reason.

One non-linear rule sits on top. When the subscriber's `churn_type` is `INVOLUNTARY`, the rounded score is then capped at `0.4000`. An involuntary churner can therefore never outrank a voluntary one above that ceiling, no matter how strong the other two factors are — we would rather fix the card than send a discount.

### 3.9. Retention Analytics: Tenure, Lifetime Value and Cohorts

Tenure is derived, never stored as an input. `tenure_days` is the difference between the clock and `first_subscribed_at` expressed in days and rounded **down** to a whole number, and is 0 while `first_subscribed_at` is null. `tenure_bucket` groups whole months, where the month count is `tenure_days` divided by 30 and rounded down: a month count of 0 or 1 gives `M0_1`, 2 or 3 gives `M2_3`, 4 through 6 gives `M4_6`, 7 through 12 gives `M7_12`, and anything above that gives `M13_PLUS`. `won_back_at` is the clock instant of the subscription creation that cited a win-back target, and null otherwise.

**Realized lifetime value** counts only settled invoices. `realized_ltv_cents` is the sum, over every invoice belonging to any subscription of this subscriber whose `status` is `PAID`, of that invoice's `amount_cents` minus its `cogs_cents`, less the sum, over every such invoice whose `status` is `WRITTEN_OFF`, of that invoice's `cogs_cents`. Invoices in `OPEN` or `FAILED` contribute nothing at all to the realized figure. A subscriber who paid one invoice and then had a second written off therefore reads lower than one who simply paid once.

**Projected lifetime value** adds a forward-looking tail. The current cycle margin is the `amount_cents` minus the `cogs_cents` of a single invoice of this subscriber — the one whose `status` is `OPEN` or `PAID`, taking the first row when those are ordered by `due_at` descending and then `created_at` descending — and is 0 when no such invoice exists. The monthly churn rate is the product of a channel base rate and a tenure multiplier. The channel base rates are 0.10 for `PAID_SOCIAL`, 0.07 for `SEARCH`, 0.12 for `AFFILIATE`, 0.05 for `ORGANIC` and 0.04 for `REFERRAL`. The tenure multipliers are 1.6 for `M0_1`, 1.2 for `M2_3`, 1.0 for `M4_6`, 0.8 for `M7_12` and 0.6 for `M13_PLUS`. The expected remaining cycles is 0 whenever the subscriber's `churn_type` is anything other than `NONE`; otherwise it is the lesser of 24 — the horizon cap — and the reciprocal of the monthly churn rate rounded half up to a whole integer. `projected_ltv_cents` is then `realized_ltv_cents` plus the current cycle margin multiplied by the expected remaining cycles, rounded half up to whole cents.

The consequence worth calling out: for a subscriber still in `NONE`, the projected figure can dwarf the realized one, while for any churned subscriber the two are identical by construction. Both figures are recomputed whenever an invoice reaches `PAID` or `WRITTEN_OFF`, whenever a subscription reaches `CANCELLED`, at win-back targeting, and at cohort snapshot time.

A **RetentionCohortSnapshot** is an immutable analytical artifact created by a `RetentionSpecialist` or `PlatformAdmin`. It requires a `cohort_month` — the acquisition month as a four-digit year, a hyphen and a two-digit month from 01 through 12, in UTC — and an `ltv_variant` of either `REALIZED` or `PROJECTED`, naming which lifetime-value figure the mean averages. Three optional filters narrow the cohort, each meaning "no restriction" when null: `acquisition_channel`, which must be one of the five channel values when present; `plan_code`, which filters on the `Plan.code` of each member's *first* subscription; and `tenure_bucket`, which must be one of the five bucket values when present and which filters on the member's `tenure_bucket` as of snapshot time.

Cohort membership is a **half-open** window. A subscriber is a member when `first_subscribed_at` is not null and falls at or after the first instant of `cohort_month` in UTC and strictly before the first instant of the following month, and when each supplied filter matches — the channel filter against `acquisition_channel`, the plan filter against the `code` of the plan of the earliest subscription by `created_at` ascending, and the bucket filter against the current `tenure_bucket`.

From that member set the snapshot derives six figures. `member_count` is the number of members after all filters. `retained_count` is the number of members holding at least one subscription whose `lifecycle_state` is `ACTIVE`, `PAUSED` or `PENDING_CANCEL`. `churned_voluntary_count` and `churned_involuntary_count` are the numbers of members whose `churn_type` is `VOLUNTARY` and `INVOLUNTARY` respectively. `retention_rate` is `retained_count` divided by `member_count`, rounded half up to four decimal places, and exactly `0.0000` when `member_count` is 0. `mean_ltv_cents` is the sum across members of the selected variant — each member's `realized_ltv_cents` when `ltv_variant` is `REALIZED`, otherwise their `projected_ltv_cents` — divided by `member_count` and rounded half up to whole cents, and exactly 0 when `member_count` is 0. `computed_at` records the clock instant of snapshot creation. The snapshot reads subscriber rows only: it never touches invoices directly, but reads the two stored lifetime-value fields.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify, settle or advance an existing resource return `200 OK`. Every response body follows the envelope of §2.2, and every request must carry the headers of §2.1. Where the Authorized Role(s) column reads "Any authenticated role", all five roles of §2.1 may call the endpoint, subject to the `Subscriber` ownership scoping described there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a plan | PlatformAdmin |
| GET | `/plans/{id}` | Read one plan | Any authenticated role |
| GET | `/plans` | List plans ordered by created_at ascending | Any authenticated role |
| POST | `/save-offer-templates` | Create a save-offer template | PlatformAdmin |
| GET | `/save-offer-templates/{id}` | Read one save-offer template | PlatformAdmin, RetentionSpecialist, ComplianceOfficer |
| POST | `/subscribers` | Register a subscriber | PlatformAdmin |
| PATCH | `/subscribers/{id}` | Update the marketing contact preference | Subscriber, PlatformAdmin |
| GET | `/subscribers/{id}` | Read one subscriber, including both lifetime-value variants and the suppression window | Any authenticated role |
| POST | `/payment-methods` | Attach a payment method | Subscriber, PlatformAdmin |
| POST | `/payment-methods/{id}/updater-result` | Ingest the card-updater network response | BillingOperator |
| GET | `/payment-methods/{id}` | Read one payment method | Any authenticated role |
| GET | `/payment-methods` | List payment methods ordered by created_at ascending | Any authenticated role |
| POST | `/subscriptions` | Start a subscription | Subscriber, PlatformAdmin |
| GET | `/subscriptions/{id}` | Read one subscription, including both state axes and every conserved counter | Any authenticated role |
| GET | `/subscriptions` | List subscriptions ordered by created_at ascending | Any authenticated role |
| POST | `/subscriptions/{id}/modifications` | Request a subscription modification | Subscriber, RetentionSpecialist |
| POST | `/subscriptions/{id}/renewals` | Run the renewal checkpoint for one subscription | BillingOperator |
| GET | `/subscriptions/{id}/compliance-notices` | List a subscription's compliance notices ordered by created_at ascending | Any authenticated role |
| POST | `/subscriptions/{id}/compliance-notices` | Schedule an additional compliance notice | BillingOperator, ComplianceOfficer |
| POST | `/compliance-notices/{id}/send` | Send a scheduled compliance notice | BillingOperator |
| POST | `/subscription-modifications/{id}/reverse` | Reverse an applied modification, or cancel a scheduled one | RetentionSpecialist, PlatformAdmin |
| GET | `/subscription-modifications/{id}` | Read one modification | Any authenticated role |
| GET | `/subscription-modifications` | List modifications ordered by created_at ascending | Any authenticated role |
| GET | `/invoices/{id}` | Read one invoice | Any authenticated role |
| GET | `/invoices` | List invoices ordered by created_at ascending | Any authenticated role |
| POST | `/invoices/{id}/dunning-attempts` | Schedule the next charge attempt on an invoice | BillingOperator |
| GET | `/dunning-attempts/{id}` | Read one dunning attempt | Any authenticated role |
| GET | `/dunning-attempts` | List dunning attempts ordered by created_at ascending | Any authenticated role |
| POST | `/_payments/simulate` | Test-driving capability: settle the invoice's pending charge attempt with a synthetic gateway result | PlatformAdmin, BillingOperator |
| POST | `/cancellation-sessions` | Open a cancellation session | Subscriber, RetentionSpecialist |
| GET | `/cancellation-sessions/{id}` | Read one cancellation session, including the step-budget counters | Any authenticated role |
| GET | `/cancellation-sessions` | List cancellation sessions ordered by created_at ascending | Any authenticated role |
| POST | `/cancellation-sessions/{id}/reason` | Capture or revise the cancellation reason | Subscriber, RetentionSpecialist |
| POST | `/cancellation-sessions/{id}/present-offers` | Run the save-offer selector once and present the winning offer | RetentionSpecialist |
| POST | `/cancellation-sessions/{id}/complete` | Finish the cancellation | Subscriber, RetentionSpecialist |
| GET | `/save-offer-grants/{id}` | Read one grant, including both margin variants and the exception axis | Any authenticated role |
| GET | `/save-offer-grants` | List grants ordered by created_at ascending | Any authenticated role |
| POST | `/save-offer-grants/{id}/accept` | Accept a presented save offer | Subscriber |
| POST | `/save-offer-grants/{id}/decline` | Decline a presented save offer | Subscriber |
| POST | `/save-offer-grants/{id}/margin-exception` | Decide a pending margin-floor exception | ComplianceOfficer |
| POST | `/winback-campaigns` | Create a win-back campaign in DRAFT | RetentionSpecialist |
| POST | `/winback-campaigns/{id}/launch` | Launch a draft campaign | RetentionSpecialist |
| GET | `/winback-campaigns/{id}` | Read one campaign, including its counters and version | PlatformAdmin, RetentionSpecialist, ComplianceOfficer |
| POST | `/winback-campaigns/{id}/targets` | Add one lapsed subscriber to a launched campaign | RetentionSpecialist |
| POST | `/winback-targets/{id}/send` | Send the win-back offer to an eligible target | RetentionSpecialist |
| POST | `/winback-targets/{id}/reevaluate` | Re-run the target state machine against the clock and the suppression predicates | RetentionSpecialist |
| GET | `/winback-targets/{id}` | Read one target | PlatformAdmin, RetentionSpecialist, ComplianceOfficer, Subscriber |
| GET | `/winback-targets` | List targets ordered by created_at ascending | PlatformAdmin, RetentionSpecialist, ComplianceOfficer, Subscriber |
| POST | `/retention-cohort-snapshots` | Compute and persist a cohort retention snapshot | RetentionSpecialist, PlatformAdmin |
| GET | `/retention-cohort-snapshots/{id}` | Read one cohort snapshot | PlatformAdmin, RetentionSpecialist, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_METHOD_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CANCELLATION_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_SAVE_OFFER_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_SAVE_OFFER_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_MODIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLIANCE_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_WINBACK_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_WINBACK_TARGET_NOT_FOUND` | 404 Not Found |
| `ERR_DUNNING_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_COHORT_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PLAN_RETIRED` | 422 Unprocessable Entity |
| `ERR_SUBSCRIPTION_NOT_MODIFIABLE` | 409 Conflict |
| `ERR_SESSION_ALREADY_OPEN` | 409 Conflict |
| `ERR_SESSION_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_REASON_NOT_CAPTURED` | 409 Conflict |
| `ERR_SIMPLE_CANCELLATION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_SAVE_OFFER` | 422 Unprocessable Entity |
| `ERR_TENURE_REQUIREMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_OFFER_QUOTA_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_OFFER_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_MARGIN_FLOOR_BREACH` | 422 Unprocessable Entity |
| `ERR_MARGIN_EXCEPTION_NOT_REQUIRED` | 409 Conflict |
| `ERR_SUBSCRIPTION_PAST_DUE` | 409 Conflict |
| `ERR_MODIFICATION_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_FREQUENCY_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_ADDON_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_PAUSE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PAUSE_EXCEEDS_MAX_CYCLES` | 422 Unprocessable Entity |
| `ERR_SKIP_BUDGET_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_DOWNGRADE_TARGET_MISSING` | 422 Unprocessable Entity |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 422 Unprocessable Entity |
| `ERR_RENEWAL_REMINDER_MISSING` | 422 Unprocessable Entity |
| `ERR_NOTICE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_NOTICE_COOLDOWN_ACTIVE` | 409 Conflict |
| `ERR_NOTICE_ALREADY_SENT` | 409 Conflict |
| `ERR_RENEWAL_NOT_DUE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_NO_PENDING_ATTEMPT` | 409 Conflict |
| `ERR_DUNNING_ATTEMPTS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_GRACE_PERIOD_ENDED` | 409 Conflict |
| `ERR_UPDATER_NOT_PENDING` | 409 Conflict |
| `ERR_PAYMENT_METHOD_INACTIVE` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_LAUNCHED` | 409 Conflict |
| `ERR_SUBSCRIBER_NOT_LAPSED` | 422 Unprocessable Entity |
| `ERR_WINBACK_SUPPRESSION_ACTIVE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_TARGET` | 409 Conflict |
| `ERR_TARGET_SUPPRESSED` | 409 Conflict |
| `ERR_CONTACT_CAP_EXCEEDED` | 422 Unprocessable Entity |
