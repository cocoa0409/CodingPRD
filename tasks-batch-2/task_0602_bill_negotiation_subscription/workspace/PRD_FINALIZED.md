# Bill Negotiation & Subscription Manager API — Product Requirements Document

## 1. Introduction

Households leak money through bills they forgot they signed up for, free trials that quietly convert to paid plans, and prices that drop the day after they pay. The Bill Negotiation & Subscription Manager is a back-office platform — in the spirit of Rocket Money and Trim — that closes those leaks on a member's behalf. After a member links their financial accounts, the platform ingests the recurring charges detected on those accounts, builds an inventory of subscriptions, and lets human concierge agents do the unglamorous work: cancelling subscriptions the member no longer wants, negotiating bills down with providers, and chasing refunds when a price drops or a charge is wrong.

The economic heart of the product is a **success-fee split**: the platform only earns when it actually saves the member money, taking a tiered cut of realized savings while the remainder accrues to the member. Realized savings are booked into a savings ledger, and a member may sweep their net share into a dedicated savings account. This document specifies the REST API behind that workflow — the entities, their lifecycles, the financial calculations, and the access-control and consistency rules that keep the books honest.

Because several actors touch the same case — a member initiates and disputes, a concierge agent negotiates and reviews, a platform operator suspends accounts and controls the clock — the API enforces precise ownership, state, and concurrency rules. The remainder of this document is organized into global system-wide specifications (Section 2), the business workflows where most of the domain logic lives (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than member registration and the clock-control endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing on a protected endpoint, or the role is not one the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and recognized but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `Anonymous`, `Member`, `ConciergeAgent`, and `PlatformAdmin`.

The `Anonymous` role is an opaque, unauthenticated identity not tied to any persisted entity; it exists only to register a new member and is never compared to any stored record. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare that resource's `member_id` to `X-User-ID`. When `X-User-Role` is `ConciergeAgent`, `X-User-ID` is the `id` of the acting `ConciergeAgentProfile`; it identifies which agent is performing concierge operations. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`.

Member-owned resources — a member's subscriptions, negotiation cases, refund claims, savings ledger entries, savings accounts, linked accounts, and recurring charges — may be mutated only by their owner. When a `Member` attempts to act on a resource whose owning `member_id` is not their own `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

### 2.3. Pagination

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and represents the number of records to skip. List results are always sorted by `created_at` in ascending order. For list responses, the `meta` object carries the pagination fields `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (a boolean that is true when records remain beyond the current page).

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id`, a UUID with no type prefix. The server assigns it; clients never supply it. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.

Most resources additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that starts at its initial value and increases by one on each mutation. Two entity types are the exception: a `ConciergeAgentProfile` and a `SavingsLedgerEntry` carry only `id` and `created_at` — they have neither `updated_at` nor `version`. Wherever this document speaks of bumping a resource's `version` or refreshing its `updated_at`, it refers only to entities that carry those fields.

### 2.5. Monetary Precision and Rounding

All monetary amounts in this system are integer counts of cents. Annualization of charges and the lifetime and report rollups are exact integer arithmetic with no rounding. Where a calculation multiplies a cents amount by a fractional rate — the success-fee computation and the service-outage proration — the multiplication is performed in cents and the result is then rounded to the nearest whole cent using round-half-up (a fractional remainder of exactly one-half rounds up). Rounding is always applied after the multiplication, never before.

### 2.6. State Transitions, Cascades, and Consistency

The platform uses an immediate-consistency model: when an operation has side effects on more than one resource, all of those effects are applied together as part of the same request. State-changing operations advance a resource from one named status to another only when the resource is currently in an allowed source state; an attempt from a disallowed state is rejected with `ERR_INVALID_STATE` (HTTP 409). Each such transition refreshes the resource's `updated_at` and bumps its `version` (for entities that carry those fields). Several transitions cascade into sibling entities — booking a ledger entry, recomputing a member's lifetime totals, adjusting an agent's open-case count, or moving a savings balance — and Section 3 specifies each cascade in full at the workflow where it occurs.

### 2.7. Optimistic Concurrency Control

Two member-initiated operations are guarded by optimistic concurrency control, because concierge activity can advance the underlying resource between the moment a member reads it and the moment they act.

The first is the cancel-request operation on a subscription. A member requesting cancellation of a subscription must include `expected_subscription_version` in the request body, carrying the `version` of the subscription as the member last observed it. If that value does not equal the subscription's current `version` — for example, because a concierge agent has since flipped the subscription to `CANCEL_REQUESTED` and then to `CANCEL_FAILED`, each bumping the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the member must re-read the subscription before retrying.

The second is the dispute operation on a refund claim. A member disputing a denied claim must include `expected_refund_claim_version`, carrying the `version` of the claim as last observed. If a concierge re-review has advanced the claim's `version` in the meantime, the value is stale and the dispute is rejected with `ERR_STALE_VERSION` (HTTP 412). All other write endpoints do not take a version field and are not subject to this check.

### 2.8. Nested Path Resolution

Path-referenced resources are validated left to right. When a request targets a resource by `{id}` in the URL and that resource does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). When a write body names another resource by a foreign-key field — for instance a `member_id`, `recurring_charge_id`, `linked_account_id`, `assigned_agent_id`, `savings_account_id`, `negotiation_case_id`, or `refund_claim_id` — and that referenced resource does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.9. Request Validation Ordering

When more than one validation could fire for a single request, checks are evaluated in a fixed priority order so that the same failing request always produces the same error. The order is: first authentication of the headers (`ERR_UNAUTHENTICATED`); then role permission (`ERR_FORBIDDEN_ROLE`); then resource ownership for member-owned mutations (`ERR_NOT_RESOURCE_OWNER`); then existence of path-referenced resources (`ERR_NOT_FOUND`); then resolution of body foreign keys (`ERR_FK_NOT_FOUND`); then presence, typing, and enum-membership of required body fields (`ERR_INVALID_REQUEST`); then numeric range checks (`ERR_VALUE_OUT_OF_RANGE`); then the state-transition check that the resource is in an allowed source state (`ERR_INVALID_STATE`); then cross-entity referential preconditions on linked resources (`ERR_LINKED_RESOURCE_STATE`). The remaining domain-specific business checks — charge-in-use, agent capacity, round and dispute caps, fiscal ceilings, trial requirements, savings-destination availability, optimistic-concurrency staleness, and member suspension — are described inline with the workflows they guard in Section 3.

### 2.10. The Logical Clock

The platform keeps a single logical clock, `SystemClock`, whose `current_utc` value governs every time-dependent decision in the system — most importantly whether a free-trial reminder is due and what timestamp is stamped onto cancellations and transfers. At server startup the clock reads exactly `2026-01-01T00:00:00Z`; before any explicit clock-set call it holds this default and never falls back to wall-clock time. A platform operator may advance it by supplying a new instant as `to_iso8601`.

## 3. Business Logic & Workflows

### 3.1. Members, Suspension, and the Savings Destination

A member joins the platform through registration, supplying their `email` and `full_name`; the email must be unique among members. Registration may optionally include `success_fee_pct`, the member's contracted display share, which when supplied must be strictly greater than zero and strictly less than one (a value at or below zero or at or above one is rejected with `ERR_VALUE_OUT_OF_RANGE`). If omitted it defaults to 0.40. This `success_fee_pct` is a contract and display hint only; it is **not** the rate used to compute the platform's fee — that rate comes from a platform tier table described in Section 3.6. A new member's `status` is `ACTIVE`.

A member's `status` is either `ACTIVE` or `SUSPENDED`. A platform operator may suspend an `ACTIVE` member, transitioning their `status` to `SUSPENDED`, and may reinstate a `SUSPENDED` member back to `ACTIVE`; each action bumps the member's `version`. A suspended member cannot initiate negotiations, request a cancellation, dispute a claim, or transfer savings — any such member-initiated attempt while suspended is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 403).

To receive swept savings, a member opens a `SavingsAccount` by supplying its owning `member_id` and a `nickname`. A new account opens with `status` of `OPEN` and a `balance_cents` of zero. The account's `balance_cents` is a running balance that only ever increases through this API as savings are transferred in; it is never decreased except by an explicit reversal of a prior transfer. A member may close an account, moving its `status` to `CLOSED`; a closed account rejects transfers. A member designates a savings destination by setting their own `savings_account_id`, which must reference a savings account belonging to that same member. The two computed lifetime fields a member carries — `lifetime_gross_savings_cents` and `lifetime_member_savings_cents` — both start at zero and are maintained by the rollup described in Section 3.7. A member's savings report may also be requested; the report computation is specified in Section 3.8.

### 3.2. Linking Accounts and Detecting Recurring Charges

A member links a financial account by supplying its `member_id`, an `institution_name`, and an `account_type` that is either `CHECKING` or `CREDIT_CARD`. A new `LinkedAccount` opens with `status` of `LINKED`. A member may unlink an account, moving its `status` to `UNLINKED`, which stops charge detection on it. Each linked account tracks a computed `detected_charge_count` — the number of recurring charges detected on it whose status is not `DISMISSED` — beginning at zero.

Recurring charges are ingested against a linked account. Ingestion supplies the `linked_account_id`, a normalized `merchant_name`, the per-cycle `amount_cents` (which must be at least 1, else `ERR_VALUE_OUT_OF_RANGE`), a `cadence`, an optional `category`, and the `first_seen_utc` timestamp at which the charge was first observed. The `cadence` is one of `MONTHLY`, `ANNUAL`, or `WEEKLY`. The `category` is one of `STREAMING`, `TELECOM`, `INSURANCE`, `UTILITY`, `SOFTWARE`, or `OTHER`, defaulting to `OTHER` when omitted. A newly ingested charge has `status` `DETECTED`, and ingestion increments the owning linked account's `detected_charge_count` by one.

Upon ingestion the charge's `annualized_cost_cents` is computed from its `amount_cents` and `cadence`. The annualization is exact integer cents with no rounding: a `MONTHLY` charge annualizes to its amount multiplied by twelve months per year; an `ANNUAL` charge annualizes to its amount unchanged (multiplied by one); and a `WEEKLY` charge annualizes to its amount multiplied by fifty-two weeks per year. The weekly case uses exactly fifty-two weeks — not the number of weeks implied by dividing 365 days by 7 — and this is the boundary that distinguishes correct annualization from a naive twelve-times rule.

A charge moves through a small lifecycle. A member may **confirm** a `DETECTED` charge, advancing its `status` to `CONFIRMED`; this is the member affirming the charge is real before any further action is taken against it. Confirmation is permitted only when the charge is currently `DETECTED` and the linked account it sits on is still `LINKED`; if the linked account is not `LINKED` the confirmation is rejected with `ERR_LINKED_RESOURCE_STATE`. Confirmation recomputes the charge's `annualized_cost_cents` using the same annualization rule. A member may also **dismiss** a charge: a `DETECTED` charge may be dismissed unconditionally, and a `CONFIRMED` charge may be dismissed only when no subscription, negotiation case, or refund claim references it in a non-terminal state — attempting to dismiss a `CONFIRMED` charge that is still in use that way is rejected with `ERR_CHARGE_IN_USE`. Dismissal advances `status` to `DISMISSED` and decrements the owning linked account's `detected_charge_count` by one. `DISMISSED` is terminal.

A subscription, negotiation case, or refund claim may be opened against a charge only when that charge is `CONFIRMED`; opening any of them against a charge that is not `CONFIRMED` is rejected with `ERR_LINKED_RESOURCE_STATE`.

### 3.3. Subscription Inventory, Cancel-on-Behalf, and Trial Reminders

A member creates a subscription to track a confirmed charge by supplying the `member_id`, the `recurring_charge_id` of the confirmed charge, a `plan_name`, and the provider's `monthly_cost_cents` (which must be at least zero). Trial-related inputs are optional: `is_free_trial` (a boolean, defaulting to false), `trial_end_utc` (when the trial converts to paid), and `trial_reminder_lead_days` (how many days before the trial's end a reminder becomes due, defaulting to 3 and required to be at least zero). When `is_free_trial` is true, `trial_end_utc` must be supplied; a trial subscription created without it is rejected with `ERR_TRIAL_END_REQUIRED`. A new subscription has `status` `ACTIVE`.

Each subscription carries a computed `reminder_due` flag. A reminder is due when the subscription is a free trial, the logical clock has reached or passed the instant that is `trial_reminder_lead_days` days before `trial_end_utc`, and the subscription has not yet been cancelled. In other words, once `current_utc` is at or after `trial_end_utc` minus the lead-day window, `reminder_due` becomes true for an uncancelled trial. This flag is recomputed against the current clock whenever a subscription is read individually or listed, and subscriptions may be filtered by `reminder_due`.

Cancel-on-behalf is a multi-party lifecycle. A member requests cancellation of an `ACTIVE` subscription; this requires the member to be `ACTIVE` and to supply a matching `expected_subscription_version` as described in Section 2.7, and it advances the subscription's `status` to `CANCEL_REQUESTED` while bumping its `version`. A concierge agent then resolves the request with the provider: confirming cancellation advances a `CANCEL_REQUESTED` subscription to `CANCELLED`, stamps `cancelled_utc` with the current clock value, sets `reminder_due` to false, and bumps the `version`; alternatively, marking the cancellation failed advances a `CANCEL_REQUESTED` subscription to `CANCEL_FAILED` and bumps the `version`. A failed cancellation is not the end: a member may re-request cancellation of a `CANCEL_FAILED` subscription, which (again requiring the member to be `ACTIVE` and to supply a matching `expected_subscription_version`) returns the subscription to `CANCEL_REQUESTED` and bumps the `version`. This retry loop may repeat. `CANCELLED` is the terminal state; the field `cancelled_utc` is populated only on confirmed cancellation.

### 3.4. Concierge Agents and Case Capacity

A platform operator creates a concierge agent profile by supplying a `display_name` and an optional `max_open_cases`, which caps how many negotiation cases the agent may simultaneously own and defaults to 5 (and must be at least 1). The profile tracks a computed `open_case_count` — the number of negotiation cases assigned to the agent whose status is `OPEN`, `PROPOSED`, or `COUNTERED` — starting at zero. A concierge agent profile carries only an `id` and `created_at`; it has no `updated_at` and no `version`.

When a new negotiation case is opened and assigned to an agent, that agent's `open_case_count` may not already be at or above their `max_open_cases`; an attempt to open a case for an agent already at capacity is rejected with `ERR_AGENT_CAPACITY_EXCEEDED`. Opening a case increments the agent's `open_case_count`, and every transition that takes a case to a terminal outcome — won, lost, or member-cancelled — decrements it by one.

### 3.5. Negotiation Rounds

A member opens a negotiation case against a confirmed charge by supplying the `member_id`, the `recurring_charge_id`, and the `assigned_agent_id` of the concierge who will own it; the member must be `ACTIVE` to do so. A new case has `status` `OPEN`. At open, the system snapshots the charge's current `annualized_cost_cents` into the case's `baseline_annual_cost_cents` — an immutable baseline that all savings are measured against — and increments the assigned agent's `open_case_count`. The fields `current_offer_annual_cost_cents`, `agreed_annual_cost_cents`, `gross_annual_savings_cents`, `success_fee_cents`, and `member_net_savings_cents` are not yet meaningful; the three computed money fields read zero and `round_count` starts at zero.

Negotiation proceeds in rounds driven by the assigned concierge agent and is cyclic. From `OPEN`, the agent **proposes** an offer by supplying `offered_annual_cost_cents` (which must be at least zero); this advances the case to `PROPOSED`, sets `current_offer_annual_cost_cents` to that offered amount, increments `round_count` by one, and bumps the `version`. From `PROPOSED`, the agent may record a provider **counter** by supplying `counter_annual_cost_cents` (at least zero); this advances the case to `COUNTERED`, sets `current_offer_annual_cost_cents` to the countered amount, and bumps the `version`. From `COUNTERED`, the agent may propose again by supplying `offered_annual_cost_cents` (at least zero), returning the case to `PROPOSED`, updating `current_offer_annual_cost_cents`, incrementing `round_count`, and bumping the `version`. This propose-counter cycle repeats up to a ceiling: the negotiation round cap is **eight rounds**, and an attempt to propose or counter once `round_count` has reached or exceeded that cap is rejected with `ERR_MAX_ROUNDS_REACHED`.

The agent closes the negotiation in one of three ways. **Accepting** the current offer wins the case: it is permitted from either `PROPOSED` or `COUNTERED`, and only when `current_offer_annual_cost_cents` is at most `baseline_annual_cost_cents` — accepting an offer whose annual cost exceeds the baseline is rejected with `ERR_OFFER_ABOVE_BASELINE`. Acceptance advances the case to `WON`, sets `agreed_annual_cost_cents` equal to `current_offer_annual_cost_cents`, and books savings (see Section 3.6). **Abandoning** the case advances it to `LOST` and is permitted from `OPEN`, `PROPOSED`, or `COUNTERED`; it decrements the assigned agent's `open_case_count` and bumps the `version`. Finally, the owning member may **cancel** an `OPEN` case (only while it is `OPEN`, and only by its owner), advancing it to `CANCELLED`, decrementing the agent's `open_case_count`, and bumping the `version`. `WON`, `LOST`, and `CANCELLED` are all terminal.

### 3.6. Booking Realized Savings and the Success-Fee Split

When a case is won — whether accepted from `PROPOSED` or from `COUNTERED`, the two paths behave identically — the platform realizes savings and splits them. First, `gross_annual_savings_cents` is computed as the baseline annual cost minus the agreed annual cost; the gross for a won negotiation is therefore the difference between two annual figures, and is taken as zero if that difference would be negative. Second, the platform's `success_fee_cents` is computed from this gross by the success-fee split. Third, `member_net_savings_cents` is computed as the gross savings minus the success fee. The case then books a `SavingsLedgerEntry`, the assigned agent's `open_case_count` is decremented by one, the owning member's lifetime totals are recomputed (Section 3.7), and the case's `version` is bumped.

The same success-fee split is also applied when a refund claim is approved, described in Section 3.9. There, the gross is not a delta of two figures but a single absolute amount: the approved refund. In both uses the split takes a realized gross savings amount in cents and produces a fee, in this pinned order. **Step one — choose the rate by tier on the gross**, using a single rate for the whole gross (not a marginal blend): when the gross is below 10,000 cents the rate is 0.40; when the gross is at least 10,000 cents but below 50,000 cents the rate is 0.35; and when the gross is at least 50,000 cents the rate is 0.30. **Step two — multiply then round**: the raw fee is the gross multiplied by the chosen rate, rounded half-up to whole cents (the rounding happens after the multiplication). **Step three — cap**: the fee is reduced to 20,000 cents if the rounded raw fee exceeds that cap. **Step four — floor at zero**: the final `success_fee_cents` is the capped value but never below zero. The rate used here is the platform tier table above; it is deliberately **not** the member's `success_fee_pct`, which remains a display-only contract hint.

A `SavingsLedgerEntry` booked from a won negotiation records the owning `member_id`, a `source_type` of `NEGOTIATION`, the `negotiation_case_id` of the source case, and copies the realized amounts: `gross_savings_cents`, `success_fee_cents`, and `member_net_cents` (the member's net, equal to the gross savings minus the success fee). Its `transfer_status` begins at `PENDING`, and `transferred_utc` is initially empty. A ledger entry carries only an `id` and `created_at` — it has no `updated_at` and no `version`. A ledger entry booked from a refund instead records a `source_type` of `REFUND` and a `refund_claim_id`; the `negotiation_case_id` is set only when the source is a negotiation, and the `refund_claim_id` only when the source is a refund.

### 3.7. Lifetime Savings Rollup

Each time a negotiation is won or a refund is approved, the owning member's two lifetime totals are recomputed from scratch — not incremented — so that they can never drift from the underlying records. The member's `lifetime_gross_savings_cents` is recomputed as the sum of `gross_annual_savings_cents` across all of that member's negotiation cases whose status is `WON`, plus the sum of `approved_refund_cents` across all of that member's refund claims whose status is `REFUNDED`. The member's `lifetime_member_savings_cents` is recomputed as the sum of `member_net_savings_cents` across that member's `WON` cases plus the sum of `member_net_savings_cents` across that member's `REFUNDED` claims. Only terminal, realized rows contribute. Both totals are exact integer cents.

### 3.8. The Savings Report

A member's savings report is computed on demand and aggregates both realized and pending savings for the member. The report's realized gross is the member's `lifetime_gross_savings_cents` and its realized net is the member's `lifetime_member_savings_cents`, both taken from the rollup. Total fees are the realized gross minus the realized net. The pending-transfer figure is the sum of `member_net_cents` across all of the member's savings ledger entries whose `transfer_status` is `PENDING`. The transferred figure is the sum of `member_net_cents` across the member's entries whose `transfer_status` is `TRANSFERRED`; entries whose `transfer_status` is `REVERSED` are excluded from the transferred figure. All report figures are exact integer cents. The report may be requested by the member, a concierge agent, or a platform operator.

### 3.9. Refund Pursuit and the Dispute Loop

A member files a refund claim against a confirmed charge by supplying the `member_id`, the `recurring_charge_id`, a `claim_type`, and two per-cycle amounts: `observed_old_amount_cents` (what was originally paid, at least 1) and `observed_new_amount_cents` (the lower amount now available, at least 0). The `claim_type` is one of `PRICE_DROP`, `DOUBLE_BILL`, or `SERVICE_OUTAGE`. A new claim has `status` `FILED`, a `dispute_round` of zero, and a computed `claimed_refund_cents` set at creation.

The pursued `claimed_refund_cents` is computed by claim type, never below zero. Let the per-cycle delta be the old amount minus the new amount, taken as zero if that would be negative. For a `PRICE_DROP`, the platform pursues the delta retroactively over the lookback window — the per-cycle delta multiplied by **six** already-billed cycles. For a `DOUBLE_BILL`, the platform pursues a single full duplicate charge at the old price — exactly the `observed_old_amount_cents`, once. For a `SERVICE_OUTAGE`, the platform pursues a pro-rated credit on the old amount for the outage portion of a thirty-day cycle: the old amount multiplied by **ten** outage days, divided by thirty days, rounded half-up to whole cents.

A concierge agent works the claim. Starting review advances a `FILED` claim to `UNDER_REVIEW`. From `UNDER_REVIEW`, the agent either approves or denies. **Approval** supplies `approved_refund_cents`, which must be at least zero and may not exceed the claim's `claimed_refund_cents` (an approval above the pursued amount is rejected with `ERR_REFUND_ABOVE_CLAIM`); it advances the claim to `REFUNDED`, records `approved_refund_cents`, computes the platform `success_fee_cents` on that approved amount via the success-fee split (Section 3.6), computes `member_net_savings_cents` as the approved refund minus the success fee, books a `SavingsLedgerEntry` with `source_type` `REFUND`, recomputes the member's lifetime totals, and bumps the `version`. **Denial** advances an `UNDER_REVIEW` claim to `DENIED` and bumps the `version`.

A denied claim is not necessarily the end. The owning member may **dispute** a `DENIED` claim, which re-opens the concierge dispute loop. Disputing requires the member to be the claim's owner and `ACTIVE`, requires `dispute_round` to be below the dispute cap, and requires a matching `expected_refund_claim_version` (Section 2.7). The dispute cap is **three** rounds; a dispute attempted once `dispute_round` has reached or exceeded that cap is rejected with `ERR_MAX_DISPUTE_ROUNDS_REACHED`. A successful dispute advances the claim from `DENIED` to `DISPUTED`, increments `dispute_round` by one, and bumps the `version`. From `DISPUTED`, the agent starts review again, returning the claim to `UNDER_REVIEW` (and bumping the `version`), from which it may once more be approved or denied. The loop `DENIED → DISPUTED → UNDER_REVIEW` may thus repeat up to the cap. `REFUNDED` and `DENIED` are terminal in the sense that progress out of `DENIED` is only ever via dispute; `REFUNDED` is final.

### 3.10. Sweeping Savings and Compensating Reversals

A savings ledger entry begins life `PENDING`. The owning member may **transfer** it, sweeping their net share into their designated savings account. A transfer is permitted only when the member owns the entry, the member is `ACTIVE`, the entry is still `PENDING`, the member has a `savings_account_id` set, and the referenced savings account's `status` is `OPEN`; if there is no savings destination set or the destination account is not `OPEN`, the transfer is rejected with `ERR_NO_SAVINGS_DESTINATION`. A successful transfer advances the entry's `transfer_status` to `TRANSFERRED`, stamps `transferred_utc` with the current clock value, and increments the savings account's `balance_cents` by the entry's `member_net_cents`. This is the only path by which a balance grows.

A transfer can be undone for compensation. A concierge agent may **reverse** a `TRANSFERRED` entry, but only while the savings account is `OPEN`; reversal advances the entry's `transfer_status` to `REVERSED`, decrements the savings account's `balance_cents` by the same `member_net_cents` it previously added (restoring the balance to its pre-transfer value), and clears `transferred_utc`. `TRANSFERRED` and `REVERSED` are the two outcomes of a once-pending entry, and a reversed entry's net is excluded from the transferred figure in the savings report.

## 4. Endpoint Definitions

All endpoints share the response envelope and authentication rules of Section 2. Creating a new resource returns HTTP 201; reads, list operations, and state-changing operations on existing resources return HTTP 200. The request body, the response body, and the side effects of each endpoint are specified in the workflow narratives of Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /members | Register a member | Anonymous |
| GET | /members/{id} | Get a member | Member, ConciergeAgent, PlatformAdmin |
| GET | /members | List members, filterable by savings_account_id | PlatformAdmin |
| POST | /members/{id}/suspend | Suspend a member | PlatformAdmin |
| POST | /members/{id}/reinstate | Reinstate a suspended member | PlatformAdmin |
| PATCH | /members/{id} | Set a member's savings_account_id | Member |
| GET | /members/{id}/savings-report | Computed savings report | Member, ConciergeAgent, PlatformAdmin |
| POST | /savings-accounts | Open a savings account for a member | Member |
| GET | /savings-accounts/{id} | Get a savings account | Member, ConciergeAgent, PlatformAdmin |
| GET | /savings-accounts | List savings accounts, filterable by member | Member, PlatformAdmin |
| POST | /savings-accounts/{id}/close | Close a savings account | Member |
| POST | /linked-accounts | Link a financial account | Member |
| GET | /linked-accounts/{id} | Get a linked account | Member, ConciergeAgent, PlatformAdmin |
| GET | /linked-accounts | List linked accounts, filterable by member | Member, PlatformAdmin |
| POST | /linked-accounts/{id}/unlink | Unlink an account | Member |
| POST | /recurring-charges | Ingest a detected recurring charge | Member, PlatformAdmin |
| GET | /recurring-charges/{id} | Get a recurring charge | Member, ConciergeAgent, PlatformAdmin |
| GET | /recurring-charges | List recurring charges | Member, ConciergeAgent, PlatformAdmin |
| POST | /recurring-charges/{id}/confirm | Confirm a detected charge | Member |
| POST | /recurring-charges/{id}/dismiss | Dismiss a charge | Member |
| POST | /subscriptions | Create a subscription tracking a confirmed charge | Member |
| GET | /subscriptions/{id} | Get a subscription | Member, ConciergeAgent, PlatformAdmin |
| GET | /subscriptions | List subscriptions | Member, ConciergeAgent, PlatformAdmin |
| POST | /subscriptions/{id}/request-cancel | Member requests cancel-on-behalf | Member |
| POST | /subscriptions/{id}/confirm-cancel | Concierge confirms provider cancellation | ConciergeAgent |
| POST | /subscriptions/{id}/fail-cancel | Concierge marks cancellation failed | ConciergeAgent |
| POST | /concierge-agents | Create a concierge agent profile | PlatformAdmin |
| GET | /concierge-agents/{id} | Get a concierge agent profile | ConciergeAgent, PlatformAdmin |
| GET | /concierge-agents | List concierge agent profiles | PlatformAdmin |
| POST | /negotiation-cases | Open a negotiation against a confirmed charge | Member |
| GET | /negotiation-cases/{id} | Get a negotiation case | Member, ConciergeAgent, PlatformAdmin |
| GET | /negotiation-cases | List negotiation cases | Member, ConciergeAgent, PlatformAdmin |
| POST | /negotiation-cases/{id}/propose | Agent proposes an offered annual cost | ConciergeAgent |
| POST | /negotiation-cases/{id}/counter | Agent records a provider counter | ConciergeAgent |
| POST | /negotiation-cases/{id}/accept | Agent accepts current offer; books savings | ConciergeAgent |
| POST | /negotiation-cases/{id}/abandon | Agent abandons the case | ConciergeAgent |
| POST | /negotiation-cases/{id}/cancel | Member cancels an open case | Member |
| POST | /refund-claims | File a refund claim against a confirmed charge | Member |
| GET | /refund-claims/{id} | Get a refund claim | Member, ConciergeAgent, PlatformAdmin |
| GET | /refund-claims | List refund claims | Member, ConciergeAgent, PlatformAdmin |
| POST | /refund-claims/{id}/start-review | Agent moves a claim into review | ConciergeAgent |
| POST | /refund-claims/{id}/approve | Agent approves a refund; books savings | ConciergeAgent |
| POST | /refund-claims/{id}/deny | Agent denies a claim | ConciergeAgent |
| POST | /refund-claims/{id}/dispute | Member disputes a denied claim | Member |
| GET | /savings-ledger-entries/{id} | Get a savings ledger entry | Member, ConciergeAgent, PlatformAdmin |
| GET | /savings-ledger-entries | List ledger entries | Member, ConciergeAgent, PlatformAdmin |
| POST | /savings-ledger-entries/{id}/transfer | Transfer member-net savings to the savings account | Member |
| POST | /savings-ledger-entries/{id}/reverse | Reverse a transferred entry | ConciergeAgent |
| POST | /_clock/set_current_utc | Set the logical server clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_MEMBER_SUSPENDED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VALUE_OUT_OF_RANGE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_LINKED_RESOURCE_STATE | 409 |
| ERR_CHARGE_IN_USE | 409 |
| ERR_AGENT_CAPACITY_EXCEEDED | 409 |
| ERR_MAX_ROUNDS_REACHED | 409 |
| ERR_MAX_DISPUTE_ROUNDS_REACHED | 409 |
| ERR_OFFER_ABOVE_BASELINE | 422 |
| ERR_REFUND_ABOVE_CLAIM | 422 |
| ERR_TRIAL_END_REQUIRED | 422 |
| ERR_NO_SAVINGS_DESTINATION | 409 |
| ERR_STALE_VERSION | 412 |
