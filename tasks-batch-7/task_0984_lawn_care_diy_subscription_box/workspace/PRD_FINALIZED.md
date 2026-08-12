# Lawn Care DIY Subscription API — Product Requirements Document

## 1. Introduction

Homeowners want a healthy lawn without becoming amateur agronomists. This product is a do-it-yourself lawn-care subscription in the style of Sunday: a new subscriber mails in a soil sample, receives a custom seasonal treatment plan built from the lab analysis of that sample, and then gets the right products shipped at the right time of year with reminders about when to apply them. Subscriptions renew and auto-ship on a billing cycle, customers can pause, skip, or cancel, pest and weed problems can be handled with quoted add-on orders, disappointing results can be raised as satisfaction claims, and a referral program rewards customers who bring in friends.

This document specifies the REST API that backs that experience. It covers the catalog of products with their application windows and safety buffers, the customer and lawn-profile model, the soil-testing loop with its resample cycle, plan drafting and review, the subscription lifecycle with its pause, skip, and cancellation cascades, box fulfillment and invoicing, application scheduling gated by weather advisories, the append-only customer credit ledger, and the referral pipeline. All temporal behavior in the system is driven by a server-side logical clock so that seasonal windows, quote expirations, and rolling allowances are deterministic and testable. Five roles interact with the platform — the registering public, subscribing homeowners, agronomists, warehouse operators, and platform administrators — and every rule below is written from their perspective.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The single exception is customer registration, which is an unauthenticated endpoint. If the presented role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The platform recognizes exactly five roles, spelled as follows:

- **Anonymous** — the unauthenticated caller, permitted only to register a new customer account. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- **Customer** — the subscribing homeowner who owns lawns, soil test kits, subscriptions, application tasks, add-on orders, and satisfaction claims. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's foreign-key field to `X-User-ID`, either directly (the `customer_id` stored on a lawn or subscription) or transitively through the lawn/subscription chain (a soil test through its lawn, an application task through its subscription, a claim through its subscription, an add-on through its subscription). A failed ownership comparison is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
- **Agronomist** — the lab and plan specialist who posts soil lab results, drafts and edits plans, submits them for review, and resolves satisfaction claims. When `X-User-Role` is `Agronomist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **FulfillmentOps** — the warehouse operator who creates shipment boxes and advances them through fulfillment. When `X-User-Role` is `FulfillmentOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **PlatformAdmin** — the operator with override power over the catalog, weather advisories, the logical clock, customer status, payment recording, referral revocation, and manual ledger adjustments. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Read access is broader than write access: customers may read their own resources (ownership-checked), while `Agronomist`, `FulfillmentOps`, and `PlatformAdmin` have the read visibility enumerated per endpoint in Section 4.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0. List responses are always sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filters and `has_more` indicates whether further records exist beyond the returned page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` in UUID format with no type prefix. Every resource records `created_at` as an ISO 8601 UTC timestamp with three fractional digits, and — with one exception — also carries `updated_at` in the same format and an integer `version` that starts at its initial value on creation and increments by exactly 1 on every mutation of that resource, whether the mutation comes from a direct client write or from a system cascade.

The single exception is the credit ledger: a `CreditLedgerEntry` is an append-only record that carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ledger entries; they are never modified after insertion.

Timestamps written by the system — `analyzed_at`, `activated_at`, `delivered_at`, `applied_at`, `filed_at`, `issued_at`, and the clock fields described below — are always taken from the logical clock, never from wall-clock time. Every datetime the system writes is serialized in the same ISO 8601 UTC form with exactly three fractional digits and a `Z` suffix (for example, `2026-06-05T00:00:00.000Z`); this applies equally to system-minted values such as a replacement or auto-ship box's `ship_date` and delivery-window bounds, a subscription's `next_ship_date` advanced by the auto-ship sweep, `skip_window_anchor`, and `quote_expires_at`. Datetime values supplied by the client — an operator-created box's `ship_date`, `delivery_window_start`, and `delivery_window_end`, and a subscription's `next_ship_date` at creation or patch — are parsed into instants for ordering and comparison but echoed back verbatim, exactly as submitted; likewise the clock-setting response reports `now_iso8601` as the submitted `to_iso8601` string.

### 2.5. The Logical Clock and Its Scheduled Sweeps

The platform runs on a server-side logical clock. Before any clock-setting call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. A PlatformAdmin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant.

Advancing the logical clock triggers a sweep with two side effects. First, the auto-ship sweep: each `ACTIVE` subscription whose `auto_ship` flag is true and whose `next_ship_date` is at or before the current logical time generates a `SEASONAL` shipment box built from the lines of that subscription's `ACTIVE` plan, with the box's `ship_date` set to the subscription's `next_ship_date`, a delivery window running from that ship date (inclusive) to seven days later (exclusive), and the subscription's `next_ship_date` then advanced by 90 days. Second, the quote-expiry sweep: each `QUOTED` add-on order whose `quote_expires_at` is at or before the current logical time flips to `EXPIRED`. The capability's response reports `now_iso8601` (the new logical time), `boxes_generated` (how many boxes the auto-ship sweep created), and `add_ons_expired` (how many quotes the expiry sweep retired).

### 2.6. Money, Precision, and Rounding

All monetary values in the system are integer cents — prices, charges, invoice lines, credit amounts, and balances alike. Whenever a computation produces a fractional cent, the result is rounded half up to the nearest whole cent. Percentages used in pricing and rewards are expressed as decimal fractions: a ten-percent figure appears in business rules as 0.10, a twenty-percent share as 0.20. Where a calculation below pins a rounding order (round each line before summing, for example), that order is part of the contract and alternative orders are non-conformant.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale views of a parent entity by requiring an expected-version field, and no other endpoint takes a version field.

A plan-activation request must carry `expected_lawn_version` holding the client's last observed `version` of the lawn the plan belongs to. If the lawn's current `version` has advanced since the client read it — for example because another plan for the same lawn was just activated, which legitimately bumps the lawn version — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from activating against a lawn state it has not observed.

A subscription-patch request must carry `expected_subscription_version` holding the client's last observed `version` of the target subscription. Because a pause/resume cycle or a payment-state cascade legitimately advances the subscription version, a patch whose `expected_subscription_version` does not match the subscription's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Validation Order and Error Precedence

Before the ordered checks below, every request is screened for basic well-formedness: a missing required field, a type mismatch, an invalid enum member, or a `next_ship_date` left absent while `auto_ship` is true is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

When a request fails several rules at once, the checks are evaluated in a fixed priority order so the surfaced error is deterministic. The order is:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to every endpoint except customer registration.
2. **Role permission** — the presented role must be permitted for the operation, otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Ownership** — for customer-scoped writes and reads, the acting customer must own the target resource directly or through the lawn/subscription chain, otherwise `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
4. **Existence** — path identifiers and body foreign-key references must exist, validated left to right along the URL and payload. Each missing resource surfaces its own 404 identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_LAWN_NOT_FOUND`, `ERR_SOIL_TEST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ADD_ON_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, or `ERR_PRODUCT_NOT_FOUND` when a referenced catalog sku does not exist.
5. **State preconditions** — the target resource must be in the state the operation requires (subscription `ACTIVE` or `PAUSED`, plan `DRAFT` or `PENDING_REVIEW`, shipment `DELIVERED`, task `SCHEDULED`, claim `FILED`, invoice `ISSUED` or `FAILED`, add-on `QUOTED`, customer `ACTIVE`, lawn not `ARCHIVED`), otherwise the operation's state-specific 409 error.
6. **Weather safety gate** — on application scheduling and rescheduling, the weather advisory for the scheduled date must not block application, otherwise `ERR_WEATHER_GATE_BLOCKED` (HTTP 409).
7. **Temporal windows** — an application date must sit inside the product's application window and a claim must be filed within its filing window, otherwise `ERR_APPLICATION_WINDOW_VIOLATION` or `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422).
8. **Constraint satisfaction** — category buffer gaps, delivery-window overlap, email and sku uniqueness, skip-allowance quota, and catalog resolvability: `ERR_APPLICATION_BUFFER_CONFLICT`, `ERR_DELIVERY_WINDOW_CONFLICT`, `ERR_EMAIL_TAKEN`, `ERR_SKU_TAKEN`, `ERR_SKIP_ALLOWANCE_EXHAUSTED`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INACTIVE`, `ERR_NO_SKIPPABLE_SHIPMENT`. Rejections in this band are predominantly 409; the exact status of each identifier is fixed in Section 5.
9. **Cross-entity referential state** — a plan's soil test must be `ANALYZED` at plan creation and activation (`ERR_SOIL_TEST_NOT_ANALYZED`), and a subscription's plan must be `ACTIVE` at subscription creation (`ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION`).

So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks.

---

## 3. Business Logic & Workflows

### 3.1. The Product Catalog and Application Windows

A PlatformAdmin seeds the platform by creating catalog products, each identified by a unique `sku` — reusing an existing sku is rejected with `ERR_SKU_TAKEN` (HTTP 409). Every product carries a display `name`, a `category` of exactly one of `FERTILIZER`, `WEED`, `PEST`, `SEED`, or `SOIL_AMENDMENT`, and a per-unit `list_price_cents` used when valuing treatment plans.

Because shipment pricing scales with lawn size, each product also carries three per-unit tier rates: `tier_t1_cents` for lawns under 500 square meters, `tier_t2_cents` for lawns of at least 500 but under 2,000 square meters, and `tier_t3_cents` for lawns of 2,000 square meters or more. Products in the `PEST` or `WEED` categories may additionally carry `add_on_flat_price_cents`, the flat per-unit price charged when the product is ordered as an add-on; for other categories this field is null.

Each product defines a seasonal application window through `window_start_md` and `window_end_md`, both month-and-day strings. The window is half-open: an application scheduled on the start day is inside the window, while one scheduled on the end day is already outside it. Safety between treatments is expressed per product through `conflicting_categories` — the list of categories that must keep their distance from this product on the same lawn — and `min_gap_days`, the minimum number of days that must separate this product from a conflicting-category application, defaulting to 14 when not supplied. A product's `active` flag defaults to true; an inactive product cannot appear in new plan lines or new boxes, and any attempt to reference one there is rejected with `ERR_PRODUCT_INACTIVE` (HTTP 409).

Anyone with the `Customer`, `Agronomist`, `FulfillmentOps`, or `PlatformAdmin` role may browse the catalog; the list endpoint accepts optional `category` and `active` filters alongside the standard `limit` and `offset` parameters.

### 3.2. Registration and the Referral Entry Point

Joining the platform starts with registration, the one endpoint open to an `Anonymous` caller. A new customer supplies an `email`, a `full_name`, and a `climate_zone` of `COOL`, `TRANSITION`, or `WARM` — the climate zone drives which application windows make sense for the customer's lawns. Email uniqueness is enforced case-insensitively: registering an address that differs from an existing one only by letter case is rejected with `ERR_EMAIL_TAKEN` (HTTP 409). The server mints a unique `referral_code` for the new account (shaped like `REF-XXXXXX`), initializes `credit_balance_cents` to 0, and sets the customer `status` to `ACTIVE`.

Registration optionally accepts a `referred_by_code`. When the code resolves to some existing customer's `referral_code`, the platform creates a Referral in `PENDING` status recording the `referrer_customer_id` (the code's owner), the `referee_customer_id` (the newly registered customer), and the `referral_code_used`. While the referral remains `PENDING`, it displays a flat `provisional_credit_cents` of 2,000 cents regardless of any invoice; the real reward is computed later at qualification time, as Section 3.9 describes. A code that resolves to no customer is rejected with `ERR_REFERRAL_CODE_INVALID` (HTTP 422).

Customer accounts themselves are governed by a small state machine under PlatformAdmin control. Suspending moves a customer from `ACTIVE` to `SUSPENDED` and requires the customer to be `ACTIVE`, otherwise `ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS` (HTTP 409). Reinstating moves a customer from `SUSPENDED` back to `ACTIVE` and requires the customer to be `SUSPENDED`, otherwise `ERR_CUSTOMER_NOT_SUSPENDED` (HTTP 409). Churn moves a customer from `ACTIVE` to the terminal `CHURNED` state and requires both that the customer be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS`) and that every one of the customer's subscriptions already be `CANCELLED`, otherwise `ERR_SUBSCRIPTIONS_STILL_OPEN` (HTTP 409). Each of these transitions increments the customer's `version` by 1. While a customer is `SUSPENDED`, creates on their behalf are blocked with `ERR_CUSTOMER_SUSPENDED` (HTTP 409).

### 3.3. Lawns and the Soil-Testing Journey

A customer onboards a property by creating a lawn profile with a `customer_id` that must equal the caller's `X-User-ID`, a human `label` such as "Front yard", the `lawn_size_sqm` area in square meters — which must be greater than zero and which determines the pricing tier used later for shipments — a `grass_type` of `COOL_SEASON`, `WARM_SEASON`, or `MIXED`, and a `region` key that the weather gate will match against advisories. The owning customer must be `ACTIVE`; attempting to create a lawn for a suspended customer is rejected with `ERR_CUSTOMER_SUSPENDED`. A lawn starts in `ACTIVE` status and can later be soft-deleted to `ARCHIVED`.

The soil test is where the science starts. A customer orders a kit for a lawn by its `lawn_id`; the lawn must be `ACTIVE`, otherwise `ERR_LAWN_ARCHIVED` (HTTP 409). The kit ships immediately, entering `KIT_SHIPPED` status with `reship_count` at 0 and `rejection_reason` null. When the customer mails the sample back and marks it returned, the kit moves from `KIT_SHIPPED` to `SAMPLE_RETURNED`; the kit must actually be in `KIT_SHIPPED` (`ERR_SOIL_TEST_NOT_SHIPPED`, HTTP 409), and the acting customer must own the kit's lawn (`ERR_OWNERSHIP_MISMATCH`).

An Agronomist then posts the lab outcome. This requires the kit to be in `SAMPLE_RETURNED`, otherwise `ERR_SOIL_TEST_NOT_RETURNED` (HTTP 409). An `outcome` of `ANALYZED` records the lab fields — `ph`, `nitrogen_ppm`, `phosphorus_ppm`, `potassium_ppm`, and `organic_matter_pct` — stamps `analyzed_at` from the logical clock, and moves the kit to the terminal `ANALYZED` state. An `outcome` of `REJECTED` instead records the supplied `rejection_reason`, increments `reship_count` by 1, sends a fresh kit, and cycles the kit back to `KIT_SHIPPED`. The resample loop — `SAMPLE_RETURNED` back to `KIT_SHIPPED` and forward again — is an allowed cycle and may repeat until a sample is successfully analyzed. Every transition increments the kit's `version` by 1.

Archiving a lawn is the customer's own action: patching the lawn with `status` set to `ARCHIVED`. The same patch endpoint also updates `label` and `region`. Archiving requires ownership and requires that no application task of the lawn sits in `SCHEDULED`, `FROZEN`, or `AWAITING_DELIVERY`; open applications block the archive with `ERR_LAWN_HAS_OPEN_APPLICATIONS` (HTTP 409). A successful patch increments the lawn's `version` by 1. List reads accept optional `customer_id` and `status` filters, and kit lists accept `lawn_id` and `status` filters.

### 3.4. From Soil Data to an Active Plan

With an analyzed soil test in hand, an Agronomist drafts a treatment plan. Plan creation takes the `lawn_id`, the `soil_test_id` — which must reference an `ANALYZED` kit, otherwise `ERR_SOIL_TEST_NOT_ANALYZED` (HTTP 409) — the `season_year` the plan covers, and `plan_lines`, an array of entries each naming a `product_sku`, a `qty_units` count, and a `target_month`. Every sku in the lines must resolve to an existing catalog product (`ERR_PRODUCT_NOT_FOUND`) that is active (`ERR_PRODUCT_INACTIVE`). A new plan starts in `DRAFT` status.

From the moment it is created, a plan carries a `provisional_value_cents`: the sum over its plan lines of each line's `qty_units` multiplied by the catalog `list_price_cents` of that line's sku. This provisional value is recomputed every time the plan's lines change. Two other money fields start null: `committed_value_cents`, which stays null until a subscription references the plan, and `discount_pct_locked`, which stays null until that same subscription locks it.

The review cycle is deliberately iterative. An Agronomist submits a `DRAFT` plan for review, moving it to `PENDING_REVIEW`; the plan must be `DRAFT`, otherwise `ERR_PLAN_NOT_DRAFT` (HTTP 409). Editing — which may replace `plan_lines` or change `season_year` — is accepted while the plan is `DRAFT` or `PENDING_REVIEW` and is rejected with `ERR_PLAN_NOT_DRAFT` in any other state. When supplied, new lines replace the old ones and `provisional_value_cents` is recomputed. Editing a plan that was `PENDING_REVIEW` sends it back to `DRAFT`, so the `DRAFT` to `PENDING_REVIEW` to `DRAFT` revision loop is an allowed cycle that can repeat as often as needed. Each edit or submission increments the plan's `version` by 1.

Activation is the customer's decision, and it is the moment a plan goes live. Activating requires the plan to be `PENDING_REVIEW`, otherwise `ERR_PLAN_NOT_ACTIVATABLE` (HTTP 409); requires the acting customer to own the plan's lawn (`ERR_OWNERSHIP_MISMATCH`); requires the plan's soil test to be `ANALYZED` (`ERR_SOIL_TEST_NOT_ANALYZED`); requires the lawn to be `ACTIVE` (`ERR_LAWN_ARCHIVED`); and carries the optimistic-concurrency guard on the lawn's version described in Section 2.7 — a stale `expected_lawn_version` is rejected with `ERR_STALE_VERSION` (HTTP 412). On activation the plan's `activated_at` is stamped from the logical clock, the lawn's previously `ACTIVE` plan — if one exists — flips to `SUPERSEDED`, and the newly activated plan records that predecessor in its `supersedes_plan_id` (null for a lawn's first activation). The activation increments both the plan's `version` and the lawn's `version` by 1. A superseded plan is terminal; the supersede chain is queryable through the `supersedes_plan_id` filter on the plan list, alongside `lawn_id`, `soil_test_id`, and `status` filters.

### 3.5. Subscription Lifecycle: Billing, Pause and Resume, Skips, Cancellation

A subscription begins when a customer starts one on an `ACTIVE` plan belonging to their own lawn. Creation takes `customer_id`, `plan_id` — the plan must be `ACTIVE`, otherwise `ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION` (HTTP 409) — and a `billing_cycle` of `MONTHLY` or `ANNUAL`. Choosing the billing cycle locks the plan's pricing: `discount_pct_locked` is written onto the plan as 0.10 for an `ANNUAL` cycle or 0.00 for a `MONTHLY` cycle, and `committed_value_cents` is computed as the plan's `provisional_value_cents` multiplied by one minus the locked discount, rounded half up to whole cents. With identical lines, a non-zero discount therefore yields a committed value below the provisional value.

The `auto_ship` flag defaults to true; when it is true, `next_ship_date` is required, and omitting it is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new subscription starts `ACTIVE` with `skips_used_in_window` at 0 and `skip_window_anchor` null until the first skip.

After creation the customer may patch `auto_ship`, `billing_cycle`, or `next_ship_date`. The patch carries the optimistic-concurrency guard on the subscription's own version — `expected_subscription_version`, per Section 2.7 — and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Changing `billing_cycle` re-locks the plan's committed value under the new cycle's discount, and a successful patch increments the subscription's `version` by 1.

Pausing is the customer's way to hold everything. Moving a subscription from `ACTIVE` to `PAUSED` requires it to be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`, HTTP 409) and requires ownership; the pause cascades so that each of its shipment boxes in `SCHEDULED` flips to `HELD` and each of its application tasks in `SCHEDULED` flips to `FROZEN`. Resuming moves a subscription from `PAUSED` back to `ACTIVE`, requires it to be `PAUSED` (`ERR_SUBSCRIPTION_NOT_PAUSED`, HTTP 409), and reverses the cascades: `HELD` boxes return to `SCHEDULED` and `FROZEN` tasks return to `SCHEDULED`. The pause/resume cycle between `ACTIVE` and `PAUSED` is unlimited, and each transition increments the subscription's `version` by 1.

Skipping lets a customer drop the next shipment without pausing. The allowance works on a rolling 365-day window: if `skip_window_anchor` is null, or the current logical time has reached or passed the anchor plus 365 days, the counter `skips_used_in_window` resets to 0 and re-anchors at this skip's timestamp. A skip is allowed while `skips_used_in_window` is less than 3 — so the third skip in a window succeeds and the fourth is rejected with `ERR_SKIP_ALLOWANCE_EXHAUSTED` (HTTP 422). A successful skip increments `skips_used_in_window` by 1 and flips the subscription's earliest `SCHEDULED` box — chosen by earliest `ship_date`, with ties broken by earliest `created_at` — to `SKIPPED`. If no `SCHEDULED` box exists at all, the skip is rejected with `ERR_NO_SKIPPABLE_SHIPMENT` (HTTP 409). The skip increments the subscription's `version` by 1.

Payment trouble has its own lane. When a payment failure lands on one of the subscription's invoices, an `ACTIVE` subscription moves to `PAST_DUE`; unlike a pause, boxes are not held — instead, any attempt to advance fulfillment on the subscription's boxes is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. When the failed invoice is later settled, the subscription returns from `PAST_DUE` to `ACTIVE`.

Cancellation is available from `ACTIVE`, `PAUSED`, or `PAST_DUE`, and is rejected only if the subscription is already `CANCELLED` (`ERR_SUBSCRIPTION_ALREADY_CANCELLED`, HTTP 409) or the caller does not own it. Cancellation fans out into a full cascade: every shipment box not already in `DELIVERED`, `SKIPPED`, or `CANCELLED` flips to `CANCELLED`; each such box cancellation flips its `ISSUED` invoice to `VOID` and posts a `RESTORE_VOID_INVOICE` ledger entry returning that invoice's `credit_applied_cents` to the customer; every application task not in `APPLIED` or `CANCELLED` flips to `CANCELLED`; and every `QUOTED` or `CONFIRMED` add-on order flips to `CANCELLED`, with the detach compensation for attached confirmed add-ons described in Section 3.9. The subscription's `version` increments by 1.

### 3.6. Shipment Boxes and the Fulfillment Pipeline

Boxes are the physical payload of the subscription. A `FulfillmentOps` operator — or a PlatformAdmin — creates a `SEASONAL` or `ADDON` box for an `ACTIVE` subscription; creating against a non-active subscription is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. (The third `box_kind`, `REPLACEMENT`, is never created here — it is minted only by claim resolution, as Section 3.9 explains.) Creation supplies the `subscription_id`, `box_kind`, planned `ship_date`, a delivery window from `delivery_window_start` (inclusive) to `delivery_window_end` (exclusive) as a half-open interval, and `lines`, an array of `product_sku` and `qty_units` pairs where every sku must resolve to an existing, active catalog product. The delivery window must not overlap the window of any other non-terminal box on the same subscription, though half-open adjacency — one window ending exactly when another begins — is allowed; an overlap is rejected with `ERR_DELIVERY_WINDOW_CONFLICT` (HTTP 409). A new box starts with `fulfillment_status` `SCHEDULED` and `billing_status` `PENDING`, with `delivered_at` and `final_charge_cents` null, and `source_claim_id` null unless claim resolution created it.

Every box carries a `provisional_charge_cents`, computed at creation and recomputed whenever a confirmed add-on attaches or detaches. The charge is built in a fixed order. Each product line contributes its `qty_units` multiplied by the tier rate of that sku for the lawn's size tier — `tier_t1_cents` under 500 square meters, `tier_t2_cents` from 500 up to but under 2,000, `tier_t3_cents` at 2,000 or more. Each attached `CONFIRMED` add-on contributes its `qty_units` multiplied by the sku's `add_on_flat_price_cents`. The two parts sum to a pre-discount amount. When the planned `ship_date` falls in the early-season window — its month-and-day on or after March 1 and before June 1 — a ten-percent discount applies; otherwise no discount applies. The discounted amount is rounded half up to whole cents, then clamped to a floor of 1,900 cents and a ceiling of 25,000 cents: a discounted amount below the floor charges 1,900 cents, one above the ceiling charges 25,000 cents.

Fulfillment advances one step at a time along `SCHEDULED` to `PICKING` to `SHIPPED` to `DELIVERED`, and the requested `to_status` must be the immediate next state — anything else is rejected with `ERR_INVALID_FULFILLMENT_TRANSITION` (HTTP 409). Moving into `PICKING` and moving into `SHIPPED` additionally require the subscription to be `ACTIVE`, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`; this is the rejection a `PAST_DUE` subscription's boxes meet, since their pause-free design holds them in place only through this gate.

Reaching `SHIPPED` is the billing event: the box's `billing_status` moves from `PENDING` to `INVOICED`, and the platform creates the invoice described in Section 3.8, auto-redeeming customer credit when a balance exists. Reaching `DELIVERED` stamps `delivered_at` from the logical clock and computes `final_charge_cents` — the same charge formula run again, except that the early-season test uses the actual `delivered_at` instead of the planned `ship_date`, and the lawn's size tier is re-read at delivery. A box planned inside the early window but delivered outside it — or the reverse — therefore yields a final charge different from its provisional charge for identical lines. Delivery also cascades: each attached `CONFIRMED` add-on order flips to `FULFILLED`, and each of the box's application tasks in `AWAITING_DELIVERY` flips to `SCHEDULED` with its `scheduled_date` set to the delivery date and its window fields recomputed for that year. Every advance increments the box's `version` by 1.

Alongside the operator-driven pipeline, boxes move under system cascades. A subscription pause flips `SCHEDULED` boxes to `HELD`, and a resume flips them back. A skip flips the selected `SCHEDULED` box to `SKIPPED`. A subscription cancellation flips boxes in `SCHEDULED`, `HELD`, `PICKING`, or `SHIPPED` to `CANCELLED`, and whenever such a box has an `ISSUED` invoice that invoice flips to `VOID` with a `RESTORE_VOID_INVOICE` ledger entry returning its `credit_applied_cents`. The box's two status fields are parallel dimensions on the same row: `fulfillment_status` evolves through the pipeline above while `billing_status` evolves through invoice events (`PENDING`, `INVOICED`, `PAID`, `FAILED`, `VOID`). The box list endpoint accepts `subscription_id`, `source_claim_id`, `fulfillment_status`, and `box_kind` filters.

### 3.7. Application Scheduling: Windows, Weather, and Category Buffers

Once a box arrives, the customer schedules the actual work. Creating an application task takes the `subscription_id`, the `shipment_id` of a box that must be `DELIVERED` — otherwise `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409) — and that must belong to the subscription, the `product_sku` being applied, and a `scheduled_date` in year-month-day form. The product's category is derived from the catalog, and the task's `window_start_date` and `window_end_date` are computed from the catalog product's `window_start_md` and `window_end_md` applied to the scheduled year, again as a half-open interval. A task created this way starts directly in `SCHEDULED`; `snooze_count` starts at 0 and `applied_at` stays null until the work is confirmed. (`AWAITING_DELIVERY` is reserved for tasks minted by claim resolution, which wait for their replacement box to arrive; see Section 3.9.)

Three independent guards protect every scheduling decision, and each is re-validated on every reschedule. The first is the weather gate: the platform looks up the weather advisory for the lawn's `region` on the scheduled date, and if no advisory exists for that region and date, the date is not blocked. An advisory blocks the date when its `rain_probability` is at least 0.40 (0.40 blocks, 0.39 passes, compared at two-decimal precision), when its `wind_kph` exceeds 24 (24 passes, 25 blocks), or when its `temp_high_c` is below 5 or above 32 (5 and 32 pass, 4 and 33 block). A blocked date is rejected with `ERR_WEATHER_GATE_BLOCKED` (HTTP 409).

The second guard is the product window: the scheduled date must fall on or after `window_start_date` and strictly before `window_end_date`, otherwise `ERR_APPLICATION_WINDOW_VIOLATION` (HTTP 422). The third is the category buffer on the lawn: for any existing application task of the same lawn in `SCHEDULED`, `FROZEN`, or `APPLIED` whose product category conflicts with the new product's category — conflict in either direction of `conflicting_categories` counts — the absolute difference in days between the new date and the existing task's date must be at least the new product's `min_gap_days`. A gap exactly equal to `min_gap_days` passes; a gap one day shorter fails with `ERR_APPLICATION_BUFFER_CONFLICT` (HTTP 409). With the default gap of 14 days, a conflicting application two weeks to the day away is acceptable, while thirteen days away is not.

Rescheduling is a self-loop on `SCHEDULED`: the task must be `SCHEDULED` (`ERR_APPLICATION_NOT_SCHEDULED`, HTTP 409), the acting customer must own the task's subscription, and the `new_date` must pass all three guards above. A successful reschedule writes `scheduled_date` to the new date and increments `snooze_count` by 1 — each reschedule, weather-driven or customer-driven, bumps the snooze counter — and increments the task's `version` by 1. When the work is done, the customer marks the task applied: again the task must be `SCHEDULED` (`ERR_APPLICATION_NOT_SCHEDULED`) and owned by the caller; the task moves to the terminal `APPLIED` state with `applied_at` stamped from the logical clock.

A computed read answers whether an application reminder should fire for a task's `scheduled_date`, given the weather gate and the product window. It returns `reminder_recommended` as a boolean and `blocking_reasons` as a list of the reasons that currently block the date, if any.

Weather advisories enter the system through a PlatformAdmin upsert keyed on `region` and `date`, carrying `rain_probability`, `wind_kph`, and `temp_high_c`; the pair of region and date is unique, and posting an advisory for an existing pair replaces the previous one. Advisory lists accept `region` and `date` filters, and task lists accept `lawn_id`, `subscription_id`, `shipment_id`, and `status` filters. Subscription pauses and cancellations cascade into tasks exactly as Section 3.5 describes: `SCHEDULED` to `FROZEN` on pause, `FROZEN` back to `SCHEDULED` on resume, and any of `SCHEDULED`, `FROZEN`, or `AWAITING_DELIVERY` to `CANCELLED` on cancellation.

### 3.8. Invoicing, Payments, and the Credit Ledger

Invoices are born at the shipping dock: when a box reaches `SHIPPED`, the platform creates an invoice whose `subscription_id` and `shipment_id` are copied from the box, stamps `issued_at` from the logical clock, and sets `status` to `ISSUED`. The invoice's `line_items` array is built from the box's product lines plus every attached `CONFIRMED` add-on, one invoice line each, with `product_sku`, `qty_units`, `unit_price_cents`, `line_discount_pct`, and `line_total_cents` on every line. The unit price is the sku's tier rate for the lawn's tier on product lines, or the sku's `add_on_flat_price_cents` on add-on lines. The line discount is ten percent when the box's `ship_date` falls in the early-season window — month-and-day on or after March 1 and before June 1 — and zero otherwise.

The rounding order on invoice lines is pinned: each line's total is computed as `qty_units` multiplied by `unit_price_cents` multiplied by one minus `line_discount_pct`, rounded half up to whole cents, and only then are the rounded line totals summed into `subtotal_cents`. The alternative order — summing exact values and rounding once at the end — yields different cents and is non-conformant. At issue, the customer's available credit is auto-redeemed: `credit_applied_cents` is the smaller of the customer's `credit_balance_cents` at that moment and the `subtotal_cents`, and `total_cents` is the subtotal minus the applied credit. When the applied credit is greater than zero, the redemption is posted as a `REDEEM_INVOICE` ledger entry against the customer.

A PlatformAdmin records payment outcomes against an invoice. The invoice must be `ISSUED` or `FAILED` — anything else is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409). A `SUCCEEDED` outcome moves the invoice to `PAID`, flips the box's `billing_status` to `PAID`, and, if the subscription was `PAST_DUE`, returns it to `ACTIVE`; it also runs the referral qualification check of Section 3.9. A `FAILED` outcome moves the invoice to `FAILED`, flips the box's `billing_status` to `FAILED`, and pushes an `ACTIVE` subscription to `PAST_DUE`. A failure recorded against an already `FAILED` invoice leaves the invoice in `FAILED`, the box billing in `FAILED`, and the subscription in `PAST_DUE`, while still incrementing the invoice's `version` by 1; a success against a `FAILED` invoice recovers exactly as a success against an `ISSUED` one, so the retry loop is safe. When a box cancellation voids an `ISSUED` invoice, the void posts a `RESTORE_VOID_INVOICE` ledger entry returning the invoice's `credit_applied_cents` to the customer whenever that amount is greater than zero.

The credit ledger is the platform's book of record for customer credit. Each entry records the `customer_id` whose balance it moves, an `entry_type` of exactly one of `EARN_REFERRAL`, `REVOKE_REFERRAL`, `EARN_SATISFACTION`, `REDEEM_INVOICE`, `RESTORE_VOID_INVOICE`, or `ADJUSTMENT`, a signed `amount_cents` — positive amounts earn, negative amounts redeem or revoke — and a polymorphic `reference_id` pointing at the Referral, SatisfactionClaim, or Invoice that motivated the entry, null for `ADJUSTMENT` entries which instead carry an optional operator `note`. A customer's `credit_balance_cents` is always the sum of `amount_cents` across all of that customer's entries, with no status filtering — the log is append-only. The balance never goes negative, because redemption at invoice issue is capped by the minimum rule above. Compensating pairs leave the balance unchanged: an `EARN_REFERRAL` of some amount followed by a `REVOKE_REFERRAL` of its negation restores the prior balance, and a `REDEEM_INVOICE` followed by a `RESTORE_VOID_INVOICE` of the same magnitude does the same.

A PlatformAdmin may also post a manual `ADJUSTMENT` entry — positive or negative — by supplying `customer_id`, `amount_cents`, and an optional `note`; posting it recomputes the customer's balance. Ledger reads accept `customer_id` and `entry_type` filters, and invoice reads accept `subscription_id`, `shipment_id`, and `status` filters.

### 3.9. Add-On Orders, Satisfaction Claims, and Referral Rewards

Pest outbreaks and weed invasions don't wait for the next seasonal box. A customer quotes an add-on order by supplying the `subscription_id`, an `add_on_sku`, and a `qty_units` greater than zero. The subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and the sku must resolve (`ERR_PRODUCT_NOT_FOUND`) to an active (`ERR_PRODUCT_INACTIVE`) catalog product in the `PEST` or `WEED` category that carries an `add_on_flat_price_cents` — a sku failing those shape requirements is rejected with `ERR_NOT_AN_ADD_ON_SKU` (HTTP 422). The quote's `quoted_price_cents` is the `qty_units` multiplied by the sku's `add_on_flat_price_cents`, and its `quote_expires_at` is set seven days out from creation on the logical clock. The order starts in `QUOTED` status with `attached_shipment_id` null; once the logical clock reaches `quote_expires_at`, the sweep flips a still-quoted order to `EXPIRED`.

Confirming a quote requires it to be `QUOTED` — a quote past its expiry has already been flipped to `EXPIRED` by the sweep, so expiry reaches confirmation only as the state error `ERR_ADD_ON_NOT_QUOTED` (HTTP 409) — requires the subscription to be `ACTIVE`, and requires ownership. On confirmation the order attaches to the subscription's earliest `SCHEDULED` box: among boxes in `SCHEDULED`, the one with the earliest `ship_date`, ties broken by earliest `created_at`. Attaching recomputes that box's `provisional_charge_cents` to include the add-on lines and increments the box's `version`. If no `SCHEDULED` box exists, the order stays `CONFIRMED` with `attached_shipment_id` null and attaches to the next box when one is created. Confirming increments the add-on's `version` by 1.

Cancelling an add-on is allowed from `QUOTED` or `CONFIRMED` — anything else is rejected with `ERR_ADD_ON_NOT_CANCELLABLE` (HTTP 409) — and requires ownership. When the cancelled order was attached to a box, cancellation performs a compensating detach: the order detaches from the box and the box's `provisional_charge_cents` is recomputed without the add-on. When the attached box is eventually delivered, a `CONFIRMED` order flips to `FULFILLED`. A subscription cancellation flips `QUOTED` and `CONFIRMED` orders to `CANCELLED`, applying the same detach-and-recompute compensation to attached confirmed orders. Add-on lists accept `subscription_id`, `attached_shipment_id`, and `status` filters.

When a delivery disappoints, the customer files a satisfaction claim against it, supplying `subscription_id`, `shipment_id`, a `claim_reason` of `INEFFECTIVE`, `DAMAGED`, `WRONG_PRODUCT`, or `OTHER`, and an optional `evidence_url` defaulting to null. The shipment must be `DELIVERED` (`ERR_SHIPMENT_NOT_DELIVERED`) and belong to the subscription, and the claim must be filed within 30 days of the box's `delivered_at` — filing later is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422). The claim starts in `FILED` status with `filed_at` stamped from the logical clock and `resolution_type` and `credit_amount_cents` null.

An Agronomist resolves a `FILED` claim — any other state is rejected with `ERR_CLAIM_NOT_FILED` (HTTP 409) — by choosing a `resolution_type`, and the choice selects one of three divergent side-effect branches. A `RESHIP` resolution creates a `REPLACEMENT` shipment box in `SCHEDULED` status whose `source_claim_id` points back to the claim, whose lines are copied from the original box, and whose `ship_date` is the current logical clock; creating that box also attaches any unattached `CONFIRMED` add-on orders of the subscription, recomputes the box's `provisional_charge_cents`, and creates one `AWAITING_DELIVERY` application task per replacement line to await the new box. A `CREDIT` resolution sets `credit_amount_cents` to the smaller of the shipment's `final_charge_cents` and a 10,000-cent cap, and posts an `EARN_SATISFACTION` ledger entry of that amount to the customer. A `REFUND` resolution is permitted only when the shipment's `billing_status` is `PAID` — otherwise `ERR_SHIPMENT_NOT_PAID` (HTTP 409) — and flips that billing status from `PAID` to `VOID`, posting a `RESTORE_VOID_INVOICE` ledger entry only for the invoice's `credit_applied_cents`; money already collected is returned out of band. A `DENY` selection moves the claim to `DENIED` with no further effects. Resolutions move the claim to the terminal `RESOLVED` (or `DENIED`) state and increment its `version` by 1. Claim lists accept `subscription_id`, `shipment_id`, and `status` filters.

Finally, the referral pipeline pays out. While a referral is `PENDING`, its `provisional_credit_cents` shows a flat 2,000 cents. When the referee's first invoice reaches `PAID` — and only when the referee has no earlier `PAID` invoice — the referral qualifies: `qualified_credit_cents` is computed as twenty percent of that first paid invoice's `total_cents`, rounded half up to whole cents, and capped at 5,000 cents, with the evaluation order pinned so the invoice total is computed first, then the twenty-percent share, then the cap. The qualified amount replaces the provisional one; the two are equal only when the invoice total is exactly 10,000 cents. The referral records the triggering invoice in `referee_first_invoice_id` and posts an `EARN_REFERRAL` ledger entry of `qualified_credit_cents` to the referrer — only the qualified amount is ever posted, never the provisional figure. A PlatformAdmin may revoke a referral in `PENDING` or `QUALIFIED` — any other state is rejected with `ERR_REFERRAL_NOT_REVOKABLE` (HTTP 409). Revoking a `QUALIFIED` referral posts a compensating `REVOKE_REFERRAL` ledger entry of the negated `qualified_credit_cents` to the referrer; revoking a `PENDING` one carries no compensation. Both paths end in the terminal `REVOKED` state and increment the referral's `version` by 1. Referral lists accept `referrer_customer_id`, `referee_customer_id`, `referee_first_invoice_id`, and `status` filters.

---

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Creating a new resource returns HTTP 201 with the created resource; operations that modify or transition an existing resource, and all reads, return HTTP 200. Request and response bodies follow the envelope of Section 2.2, lists follow the pagination of Section 2.3, and every write goes through the validation order of Section 2.8. The table below is a summary only — the request fields, guards, and side effects of each operation are those narrated in Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock; runs the auto-ship and quote-expiry sweeps | PlatformAdmin |
| POST | /api/catalog/products | Create a catalog product | PlatformAdmin |
| GET | /api/catalog/products/{id} | Get one catalog product | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| GET | /api/catalog/products | List catalog products | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| POST | /api/customers/register | Register a customer; mints a referral code; opens a PENDING referral when referred | Anonymous |
| GET | /api/customers/{id} | Get a customer | Customer, Agronomist, PlatformAdmin |
| POST | /api/customers/{id}/status | Suspend, reinstate, or churn a customer | PlatformAdmin |
| POST | /api/lawns | Create a lawn profile | Customer |
| GET | /api/lawns/{id} | Get a lawn | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| GET | /api/lawns | List lawns | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| PATCH | /api/lawns/{id} | Update label/region or archive the lawn | Customer |
| POST | /api/soil-tests | Order a soil test kit for a lawn | Customer |
| GET | /api/soil-tests/{id} | Get a soil test kit | Customer, Agronomist, PlatformAdmin |
| GET | /api/soil-tests | List soil test kits | Customer, Agronomist, PlatformAdmin |
| POST | /api/soil-tests/{id}/return-sample | Mark the soil sample returned | Customer |
| POST | /api/soil-tests/{id}/lab-result | Post lab outcome: analyzed fields or rejection with reship | Agronomist |
| POST | /api/plans | Draft a custom plan from an analyzed soil test | Agronomist |
| GET | /api/plans/{id} | Get a plan version | Customer, Agronomist, PlatformAdmin |
| GET | /api/plans | List plan versions | Customer, Agronomist, PlatformAdmin |
| POST | /api/plans/{id}/submit-review | Move a DRAFT plan to PENDING_REVIEW | Agronomist |
| PATCH | /api/plans/{id} | Edit plan lines or season year; sends PENDING_REVIEW back to DRAFT | Agronomist |
| POST | /api/plans/{id}/activate | Activate a reviewed plan; supersedes the lawn's previous ACTIVE plan | Customer |
| POST | /api/subscriptions | Start a subscription on an ACTIVE plan; locks the plan discount | Customer |
| GET | /api/subscriptions/{id} | Get a subscription | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| GET | /api/subscriptions | List subscriptions | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| PATCH | /api/subscriptions/{id} | Update auto-ship, billing cycle, or next ship date | Customer |
| POST | /api/subscriptions/{id}/status | Pause or resume with full box/task cascades | Customer |
| POST | /api/subscriptions/{id}/skip-next-shipment | Skip the earliest SCHEDULED box within the rolling allowance | Customer |
| POST | /api/subscriptions/{id}/cancel | Cancel; cascades to boxes, invoices, tasks, and add-ons | Customer |
| POST | /api/shipments | Create a SEASONAL or ADDON box for an ACTIVE subscription | FulfillmentOps, PlatformAdmin |
| GET | /api/shipments/{id} | Get a shipment box | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| GET | /api/shipments | List shipment boxes | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| POST | /api/shipments/{id}/advance-fulfillment | Advance fulfillment one step toward DELIVERED | FulfillmentOps |
| POST | /api/applications | Schedule an application of a delivered product | Customer |
| GET | /api/applications/{id} | Get an application task | Customer, Agronomist, PlatformAdmin |
| GET | /api/applications | List application tasks | Customer, Agronomist, PlatformAdmin |
| POST | /api/applications/{id}/reschedule | Reschedule a SCHEDULED task through the weather, window, and buffer guards | Customer |
| POST | /api/applications/{id}/mark-applied | Confirm the product was applied | Customer |
| GET | /api/applications/{id}/reminder | Computed read: whether an application reminder should fire | Customer, Agronomist, PlatformAdmin |
| POST | /api/weather-advisories | Upsert a weather advisory for a region and date | PlatformAdmin |
| GET | /api/weather-advisories | List weather advisories | Customer, Agronomist, FulfillmentOps, PlatformAdmin |
| POST | /api/add-ons | Quote a pest/weed add-on for a subscription | Customer |
| GET | /api/add-ons/{id} | Get an add-on order | Customer, Agronomist, PlatformAdmin |
| GET | /api/add-ons | List add-on orders | Customer, Agronomist, PlatformAdmin |
| POST | /api/add-ons/{id}/confirm | Confirm a quoted add-on; attaches to the earliest SCHEDULED box | Customer |
| POST | /api/add-ons/{id}/cancel | Cancel a quoted or confirmed add-on with detach compensation | Customer |
| GET | /api/invoices/{id} | Get an invoice | Customer, PlatformAdmin |
| GET | /api/invoices | List invoices | Customer, PlatformAdmin |
| POST | /api/invoices/{id}/record-payment | Record a payment outcome; drives PAST_DUE and referral qualification | PlatformAdmin |
| POST | /api/claims | File a satisfaction claim on a delivered box | Customer |
| GET | /api/claims/{id} | Get a claim | Customer, Agronomist, PlatformAdmin |
| GET | /api/claims | List claims | Customer, Agronomist, PlatformAdmin |
| POST | /api/claims/{id}/resolve | Resolve a claim via RESHIP, CREDIT, REFUND, or DENY | Agronomist |
| GET | /api/referrals/{id} | Get a referral | Customer, PlatformAdmin |
| GET | /api/referrals | List referrals | Customer, PlatformAdmin |
| POST | /api/referrals/{id}/revoke | Revoke a referral; qualified referrals post a clawback | PlatformAdmin |
| GET | /api/credit-ledger/{id} | Get one ledger entry | Customer, PlatformAdmin |
| GET | /api/credit-ledger | List ledger entries | Customer, PlatformAdmin |
| POST | /api/credit-ledger/adjustments | Post a manual ADJUSTMENT ledger entry | PlatformAdmin |

---

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in its `error_id` field, with the HTTP status fixed here. The trigger condition for each error is defined where the rule lives — in the role and validation-order rules of Section 2 and the workflow narratives of Section 3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_LAWN_NOT_FOUND | 404 |
| ERR_SOIL_TEST_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_ADD_ON_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_PRODUCT_INACTIVE | 409 |
| ERR_NOT_AN_ADD_ON_SKU | 422 |
| ERR_EMAIL_TAKEN | 409 |
| ERR_SKU_TAKEN | 409 |
| ERR_REFERRAL_CODE_INVALID | 422 |
| ERR_CUSTOMER_SUSPENDED | 409 |
| ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS | 409 |
| ERR_CUSTOMER_NOT_SUSPENDED | 409 |
| ERR_SUBSCRIPTIONS_STILL_OPEN | 409 |
| ERR_LAWN_ARCHIVED | 409 |
| ERR_LAWN_HAS_OPEN_APPLICATIONS | 409 |
| ERR_SOIL_TEST_NOT_SHIPPED | 409 |
| ERR_SOIL_TEST_NOT_RETURNED | 409 |
| ERR_SOIL_TEST_NOT_ANALYZED | 409 |
| ERR_PLAN_NOT_DRAFT | 409 |
| ERR_PLAN_NOT_ACTIVATABLE | 409 |
| ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION | 409 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 409 |
| ERR_SUBSCRIPTION_NOT_PAUSED | 409 |
| ERR_SUBSCRIPTION_ALREADY_CANCELLED | 409 |
| ERR_SKIP_ALLOWANCE_EXHAUSTED | 422 |
| ERR_NO_SKIPPABLE_SHIPMENT | 409 |
| ERR_INVALID_FULFILLMENT_TRANSITION | 409 |
| ERR_DELIVERY_WINDOW_CONFLICT | 409 |
| ERR_SHIPMENT_NOT_DELIVERED | 409 |
| ERR_APPLICATION_NOT_SCHEDULED | 409 |
| ERR_APPLICATION_WINDOW_VIOLATION | 422 |
| ERR_APPLICATION_BUFFER_CONFLICT | 409 |
| ERR_WEATHER_GATE_BLOCKED | 409 |
| ERR_CLAIM_WINDOW_EXPIRED | 422 |
| ERR_CLAIM_NOT_FILED | 409 |
| ERR_ADD_ON_NOT_QUOTED | 409 |
| ERR_ADD_ON_NOT_CANCELLABLE | 409 |
| ERR_SHIPMENT_NOT_PAID | 409 |
| ERR_INVOICE_NOT_PAYABLE | 409 |
| ERR_REFERRAL_NOT_REVOKABLE | 409 |
| ERR_STALE_VERSION | 412 |
