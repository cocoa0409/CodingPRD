# Dtc Lab Testing API — Product Requirements Document

## 1. Introduction

Consumers increasingly want to order their own laboratory tests without first visiting a physician's office, pay for them out of pocket, and receive results directly. This document specifies the API behind a direct-to-consumer lab testing platform modeled on the Quest and Labcorp OnDemand services. The platform publishes a catalog of individual test offerings and discounted panel bundles, lets a patient assemble a cart and see a self-pay price estimate, and converts a checked-out cart into an order that is fulfilled either at a patient service center (PSC) or by an at-home collection kit.

Beyond ordering and pricing, the platform carries the clinical and regulatory weight that comes with handling biological specimens and diagnostic results. Certain tests may only be drawn after an affiliated physician network (the Physician's Ordering Network, or PWN) has authorized them, and that authorization is gated on the patient's age and state of residence. Once a specimen is collected, it moves through analysis to a released result, where a critical value triggers a mandatory callback protocol before the result may be disclosed, and an abnormal or critical result may open a telehealth referral — but only when the patient has consented to share results. Money flows alongside the clinical workflow: a card or an HSA/FSA fund source is authorized at checkout against a forward-looking estimate and captured at completion against a chronological invoice that bills only the tests that actually produced results.

The sections below define the global contract that every endpoint honors (Section 2), the business workflows and the rules scattered through them (Section 3), the endpoint catalog (Section 4), and the error catalog (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under the `/catalog` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing or malforming either header is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `CatalogAdmin`, `Patient`, `OrderingPhysician`, `PhlebotomyTech`, and `LabTech`.

When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` entity. Ownership checks on any resource that references a `Patient` compare the resource's `patient_id` foreign-key field to `X-User-ID`. A `Patient` acting on a cart, an order, an order's capture or cancel action, a cart line edit, or a physician-order resubmission must own the targeted resource; when `X-User-ID` is not the owning `patient_id`, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

When `X-User-Role` is `CatalogAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same is true for `OrderingPhysician`: `X-User-ID` is an opaque operator identifier that the server records as `reviewing_physician_id` on a `PhysicianOrder` when the physician takes a review action, but does not compare to any entity's `id`. Likewise for `PhlebotomyTech`: `X-User-ID` is an opaque operator identifier that the server records as `collected_by_user_id` on a `Specimen` at collection. And for `LabTech`: `X-User-ID` is an opaque operator identifier that the server compares only against a specimen's `collected_by_user_id` to enforce segregation of duties at result release, never against any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is a real wall-clock instant and is not drawn from the logical clock of Section 2.4 (which governs only the domain-time uses enumerated there).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order; ties on `created_at` are broken by creation order (the order in which the server minted the records). On every list endpoint that a `Patient` is permitted to call, results are automatically scoped to resources the calling `Patient` owns (by the owning `patient_id`, resolved transitively through the parent cart/order where the resource itself carries no `patient_id`), so a `Patient` never sees another patient's rows; non-`Patient` roles see all rows subject to the query filters. Supplied query filters (such as `patient_id`, `cart_id`, `order_id`, `test_offering_id`, `order_line_id`, `lab_result_id`, `specimen_id`, `analyzer_code`, `psc_location_code`, or `status`) further narrow the set; an unrecognized filter value simply matches nothing.

Every list response includes the following four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Logical Clock

Every primary resource carries a system-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional digits. Resources whose definitions include lifecycle mutation additionally carry an `updated_at` timestamp (same ISO 8601 UTC format), refreshed on every mutation, and a `version` integer that begins at its initial value and increments by one on each mutation. In this domain every entity — `TestOffering`, `PanelBundle`, `Patient`, `Cart`, `CartLine`, `Order`, `OrderLine`, `PhysicianOrder`, `Appointment`, `HomeKit`, `Specimen`, `LabResult`, `TelehealthReferral`, `AnalyzerRun`, and `Payment` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

All time-dependent behavior is governed by a logical clock rather than wall-clock time. The server boots with the logical clock set to exactly `2026-01-01T00:00:00Z`, and before any clock-set call it reads exactly this default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant and returns, in the success envelope's `data`, an object carrying a single `now` field holding the new logical clock instant as an ISO 8601 UTC string with three fractional digits (this clock-set response is the one success body that is not a primary resource object). The logical clock governs a specimen's `collected_at` stamp, the repeat-discount lookback window, and every appointment- and analyzer-run-slot comparison.

### 2.5. Nested Resource Resolution and Validation Ordering

Resources in this system are peers linked by foreign keys; URL paths address a single resource by its `id` and do not nest. Even so, a write may reference several resources at once — a body that names a `cart_id`, an `order_id`, a `lab_result_id`, or similar. The server resolves every path and body identifier left to right, and the first identifier that fails to resolve causes immediate rejection with `ERR_NOT_FOUND` before any business rule runs.

Validation across the whole API follows a fixed precedence so that two implementations reject the same request with the same code. Header presence and well-formedness is checked first (`ERR_MISSING_USER_CONTEXT`); then role permission for the operation (`ERR_FORBIDDEN_ROLE`); then, for a `Patient` acting on an owned resource, that `X-User-ID` equals the resource's `patient_id` (`ERR_NOT_RESOURCE_OWNER`); then existence of every referenced identifier (`ERR_NOT_FOUND`); then request-body well-formedness — required fields present, enum values within their domain, and integers non-negative where required (`ERR_INVALID_REQUEST`); then, where an optimistic-concurrency version is supplied or required, the version match (a 412 stale-version rejection); then the target resource's state admits the requested transition (a 409 state error); and finally the domain-specific business rules described throughout Section 3. Crucially, the optimistic-concurrency version check runs before any state precondition on the same parent.

### 2.6. Hierarchical Consistency and Cascades

A single operation in this domain frequently mutates more than one resource, and each such cascade is part of the contract. Whenever the server changes a resource, it refreshes that resource's `updated_at` and increments its `version`. When a physician declines an authorization, when a specimen is rejected, when a result is released, and when an order is cancelled, the effects propagate from the triggering resource outward to the order lines, specimens, the parent order's two status axes, and the payment — each cascade hop is enumerated in the relevant workflow in Section 3. The server performs these propagations automatically without requiring a separate client request against each affected resource. An order's fulfillment status is therefore never set directly by a client; it is always recomputed by the server as its order lines reach terminal outcomes.

### 2.7. Self-Pay Pricing, Precision, and Rounding

All monetary amounts are integer cents and are never negative where the field is declared non-negative. Pricing is computed at two distinct moments with two distinct input sets — a forward-looking cart estimate over all lines and a chronological order invoice over only the lines that produced results — but both use the same arithmetic, described in Sections 3.3 and 3.6. Rounding is applied with the round-half-up method, and it is applied at each pinned rounding point rather than once at the end: first when a per-line repeat discount is taken, and again when the platform tier discount is computed. Because rounding is performed per line and then summed (not summed and then rounded), the order of operations is fixed and must be honored exactly.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a version of the parent it has actually observed.

Placing an order from a cart requires the request body to carry `expected_cart_version`, holding the client's last observed `version` of the source `Cart`. Adding or removing a cart line, or changing a cart's fund source, legitimately re-prices the cart and increments `Cart.version`; if the cart's current `version` has advanced past the value the client supplies, the checkout is carrying a stale quote and is rejected with `ERR_STALE_CART_VERSION` (HTTP 412), so the client cannot lock in an outdated estimate.

Capturing payment on an order requires the request body to carry `expected_order_version`, holding the client's last observed `version` of the target `Order`. A result release or specimen rejection legitimately recomputes the order's invoiced total and patient-due amount and increments `Order.version`; if the order's current `version` has advanced past the supplied value, the capture would settle an outdated amount and is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The same `expected_order_version` field and the same `ERR_STALE_ORDER_VERSION` (HTTP 412) rejection apply when cancelling an order. No other endpoint accepts a version field, and endpoints that do not appear in these rules perform no version check.

### 2.9. Segregation of Duties and Data Privacy

Two safety principles cut across the clinical workflow. First, segregation of duties: the operator who releases a result must not be the operator who collected its specimen. Whenever a result is released, the releasing `X-User-ID` is compared to the specimen's `collected_by_user_id`, and if they are equal the release is rejected with `ERR_SOD_COLLECTOR_CANNOT_RELEASE`. Second, data privacy: a patient's results may be disclosed to a telehealth referral only when the patient's `consent_share_results` flag is true. A manual referral creation against a patient who has not consented is rejected with `ERR_CONSENT_REQUIRED`; the automatic referral that a result release would otherwise spawn is simply skipped — silently, with no error — when consent is absent.

## 3. Business Logic & Workflows

### 3.1. Curating the Catalog: Test Offerings and Panel Bundles

A `CatalogAdmin` builds and maintains the catalog. A **test offering** is created with a catalog `test_code`, a patient-facing `display_name`, a self-pay `list_price_cents` that must be greater than zero, and a `specimen_type` that is one of `BLOOD`, `URINE`, or `SALIVA`. Two boolean attributes, `home_kit_eligible` and `requires_fasting`, each default to false and govern fulfillment: the former permits at-home collection, the latter forces a fasting attestation at scheduling. An offering may declare clinical bounds used later to flag results — `critical_low`, `critical_high`, `ref_low`, and `ref_high` — and any of these may be omitted (a null bound simply does not constrain that side). A newly created offering is minted with `status` set to `ACTIVE`. A `test_code` must be unique among non-`ARCHIVED` offerings; a collision is rejected with `ERR_DUPLICATE_CODE`.

An offering may be soft-deleted by archiving it, moving its `status` from `ACTIVE` to `ARCHIVED`. An `ARCHIVED` offering remains queryable — listing includes archived offerings only when `include_archived` is requested, and the offering list also accepts a `status` filter — but it can no longer be added to a cart.

A **panel bundle** groups offerings at a flat price. It is created with a `bundle_code`, a `display_name`, an ordered `member_test_codes` array, and a `bundle_price_cents` greater than zero that substitutes for the sum of the members' list prices when every member is present in a cart. The members must be at least two distinct codes, and each must reference an `ACTIVE` offering at create time; a bundle that violates either rule is rejected with `ERR_INVALID_BUNDLE_MEMBERS`. A `bundle_code` must be unique among non-`ARCHIVED` bundles, again under `ERR_DUPLICATE_CODE`. A bundle is minted `ACTIVE` and may later be `ARCHIVED`.

A patient is registered with a unique `email`, a `full_name`, a `date_of_birth` as an ISO `YYYY-MM-DD` date, a two-letter `state_code` of residence, an optional starting `hsa_balance_cents` (defaulting to 0 and never negative), and an optional `consent_share_results` flag (defaulting to false). A duplicate email is rejected with `ERR_DUPLICATE_CODE`. A patient is minted with `status` `ACTIVE`. A patient — or an admin acting for them — may later update `consent_share_results` and/or `hsa_balance_cents`.

### 3.2. Assembling a Cart

A `Patient` opens a cart by supplying their `patient_id` and an optional `fund_source`, which is either `CARD` or `HSA_FSA` and defaults to `CARD`. A new cart begins in `status` `OPEN` with `line_count`, `subtotal_cents`, `estimated_total_cents`, `estimated_hsa_applied_cents`, and `estimated_patient_due_cents` all initialized to zero.

To add a line, the patient names the owning `cart_id` and the `test_offering_id` of the offering to add. The offering must be `ACTIVE` and the cart must be `OPEN`; otherwise the add is rejected with `ERR_OFFERING_NOT_ADDABLE`. On a successful add, the line snapshots the offering's `test_code` into the line's own `test_code` and the offering's `list_price_cents` into `unit_list_price_cents`, sets `line_count` up by one, recomputes the cart's totals, and increments `Cart.version` by one. Removing a line is permitted only on an `OPEN` cart; it sets `line_count` down by one, recomputes totals, and likewise increments `Cart.version` by one. Changing a cart's `fund_source` re-runs the estimate and also increments `Cart.version` by one.

Each line records whether it qualified for a repeat discount in `repeat_discount_applied`. This flag is set true when, at the moment the line is added, the patient already has a `RELEASED` lab result for the same `test_code` whose release falls within the lookback window — that is, within the 365 days immediately before the cart was created. The result's release instant is read from that lab result's `updated_at` (the moment it transitioned to `RELEASED`), and the window is the closed interval `[cart.created_at − 365 days, cart.created_at]`, inclusive at both ends. Otherwise the flag is false. The flag is computed once, from the patient's released history, when the line is added.

### 3.3. The Cart Estimate: Forward-Looking Self-Pay Quote

Whenever a line is added or removed, and whenever a cart is read, the cart estimate is recomputed over all lines in the `OPEN` cart, with each line counted once. The estimate assumes every line will be fulfilled, and it proceeds in four pinned steps.

The first step is bundle substitution. The server considers each `ACTIVE` panel bundle in a deterministic order — sorted by `bundle_code` ascending, and where two share a code, by `created_at` ascending. Starting from the multiset of the cart's line test codes, a bundle qualifies if every one of its `member_test_codes` still has an unmatched line available; when it qualifies, the bundle's `bundle_price_cents` is added to the running subtotal and those member lines' codes are consumed so no later bundle or line reuses them.

The second step prices each line that no bundle consumed. For such a line, the base is its `unit_list_price_cents`. If the line's `repeat_discount_applied` is true, the line's net price is the base multiplied by one minus the repeat discount rate of 0.15 — that is, fifteen percent off — rounded half-up to a whole cent at this point, per line. If the flag is false, the line's net price is simply its base. Each line's net price is added to the subtotal. The rounding happens per line and the results are then summed; it is never summed first and rounded once.

The third step applies a platform tier discount keyed on the resulting subtotal. When the subtotal is at least 50000 cents (five hundred dollars), the platform rate is 0.15; otherwise, when the subtotal is at least 20000 cents (two hundred dollars), the platform rate is 0.10; otherwise the rate is zero. The platform discount is the subtotal multiplied by that rate, rounded half-up to a whole cent, and `estimated_total_cents` is the subtotal minus that rounded discount. The pre-discount subtotal after bundle substitution is stored in `subtotal_cents`.

The fourth step applies HSA/FSA funds. When the cart's `fund_source` is `HSA_FSA`, `estimated_hsa_applied_cents` is the smaller of the patient's `hsa_balance_cents` and `estimated_total_cents`; when the fund source is `CARD`, it is zero. In either case, `estimated_patient_due_cents` is `estimated_total_cents` minus `estimated_hsa_applied_cents`.

### 3.4. Checkout: Turning a Cart Into an Order

A `Patient` places an order from their cart. The request names the source `cart_id`, the `fulfillment_mode` (either `PSC` or `HOME_KIT`), and `expected_cart_version`. Checkout is refused on an empty cart — a `line_count` of zero yields `ERR_EMPTY_CART` — and the supplied `expected_cart_version` must match the cart's current `version` or the placement is rejected with `ERR_STALE_CART_VERSION`, as described in Section 2.8.

On success, the source cart's `status` moves to `CHECKED_OUT`, and the new order is minted carrying the buyer's `patient_id`, the source `cart_id`, the chosen `fulfillment_mode`, and a snapshot of the cart's `fund_source` into the order's own `fund_source`. For each cart line the server mints an order line in `status` `ORDERED`, carrying that line's `order_id`, the `test_offering_id`, and snapshots of `test_code`, `unit_list_price_cents`, and `repeat_discount_applied`. Each order line's `requires_physician_order` is set according to the network-restriction rule in Section 3.5: it is true exactly when the offering's `test_code` is PWN-restricted. For every restricted line the server mints a `SUBMITTED` physician order. The order's `payment_status` axis begins at `AUTH_PENDING`; as part of order placement, once the payment is authorized, the axis advances from `AUTH_PENDING` to `AUTHORIZED`, so a freshly placed order is observed with `payment_status` at `AUTHORIZED` and its `fulfillment_status` at `AWAITING_COLLECTION`. Concurrently a `Payment` is minted in `status` `AUTHORIZED`, with `fund_source` snapshotting the order's fund source and `authorized_amount_cents` set to the cart's `estimated_patient_due_cents` captured at this moment; its `captured_amount_cents` and `hsa_drawn_cents` both start at zero and are filled in only at capture. The order's own `invoiced_total_cents`, `hsa_applied_cents`, and `patient_due_cents` start at zero and are filled in only as results are released.

When the `fulfillment_mode` is `HOME_KIT`, the server validates shipping eligibility at checkout as described in Section 3.5; a `PSC` order instead expects a booked and checked-in appointment before any specimen may be drawn.

### 3.5. The Physician's Ordering Network, Fulfillment Eligibility, and Specimen Collection

A test offering is **PWN-restricted** — meaning a restricted line cannot be collected until an `APPROVED` physician order exists for it — if and only if its `test_code` begins with the case-sensitive prefix `TST`. Every other code is unrestricted. This single rule determines each order line's `requires_physician_order` at checkout.

An `OrderingPhysician` reviews a submitted physician order and renders a `decision` that is one of `APPROVE`, `DECLINE`, or `REQUEST_INFO`, optionally attaching a `clinical_note`. The physician order also carries the `order_line_id` of the line it authorizes, the `patient_id` derived from that line's order, and — set on the first review action — the `reviewing_physician_id` taken from the physician's `X-User-ID`. A decision is allowed only while the order is `SUBMITTED`; an attempt against any other state is rejected with `ERR_PHYSICIAN_ORDER_NOT_REVIEWABLE`. Approving moves the order from `SUBMITTED` to `APPROVED` and thereby satisfies the collection gate for its line, but only after two further checks: the patient's `state_code` must be one of the network-licensed states — `CA`, `TX`, or `FL` — or the approval is rejected with `ERR_PWN_STATE_UNLICENSED`; and the patient's age, derived as the logical-clock today minus `date_of_birth`, must be at least 18 years, or the approval is rejected with `ERR_PWN_AGE_INELIGIBLE`. Requesting more information moves the order from `SUBMITTED` to `NEEDS_MORE_INFO` and records the reviewing physician. Declining moves the order from `SUBMITTED` to `DECLINED`, records the reviewing physician, and triggers the decline cascade described below.

A `Patient` may resubmit an order that sits in `NEEDS_MORE_INFO`, moving it back to `SUBMITTED` for re-review and, when a new `clinical_note` is supplied, overwriting the stored note; this is the cyclic loop where a request-info round returns the order to `SUBMITTED`. A resubmission attempted on an order in any other state is rejected with `ERR_PHYSICIAN_ORDER_NOT_RESUBMITTABLE`.

When a physician declines, three cascade hops follow in order: the owning order line transitions from `ORDERED` to `REJECTED` (hop 1); that rejection bubbles up to recompute the parent order's `fulfillment_status` (hop 2); and if every other order line is already terminal, the order's `fulfillment_status` resolves per the order cascade rule of Section 3.7 (hop 3): it advances to `COMPLETED` only when at least one line is `RESULTED`; when every line is terminal but none is `RESULTED` (all `REJECTED`/`CANCELLED`), the recompute leaves `fulfillment_status` unchanged — automatic resolution never sets `CANCELLED`, which arises only from the explicit cancel action of Section 3.7. A declined line is excluded from the order invoice.

Specimen collection is performed by a `PhlebotomyTech`, either as a PSC draw or by accessioning a returned home kit. Collection advances an order line from `ORDERED` to `COLLECTED` and is permitted only when several conditions hold: the line must be in `ORDERED`, or the attempt is rejected with `ERR_ORDER_LINE_NOT_COLLECTIBLE`; the parent order's `fulfillment_status` must be `AWAITING_COLLECTION` or `IN_PROCESSING`, or the attempt is rejected with `ERR_ORDER_NOT_COLLECTABLE_STATE`; if the line's `requires_physician_order` is true, an `APPROVED` physician order must exist for the line, or it is rejected with `ERR_PHYSICIAN_ORDER_REQUIRED`; and for a PSC order, a `CHECKED_IN` appointment must exist for the order, or it is rejected with `ERR_APPOINTMENT_NOT_CHECKED_IN`. On success the server mints a `Specimen` in `status` `COLLECTED`, stamps `collected_by_user_id` with the collecting `X-User-ID`, `collected_at` with the logical clock, an `order_line_id` linking it to the line it fulfills, and a system-minted `accession_code`. Because this action mints a stand-alone `Specimen`, it returns `201 Created` with the new `Specimen` (not the order line) in `data`. If the order was in `AWAITING_COLLECTION`, this first collect advances its `fulfillment_status` to `IN_PROCESSING`.

Home-kit fulfillment is constrained by geography. A home kit names the `order_id` it serves and a `shipping_state_code`, and the server mints it in `status` `SHIPPED` with a system-minted `tracking_code`. The shipping state must equal the patient's `state_code` and must not be one of the banned states — `NY`, `NJ`, or `RI` — and the offering must be `home_kit_eligible`; a violation of any of these is rejected with `ERR_HOME_KIT_STATE_BANNED`. The same eligibility check applies both at `HOME_KIT` checkout and at the home-kit minting step.

### 3.6. The Chronological Order Invoice and HSA Settlement

Where the cart estimate looks forward over all lines, the order invoice is chronological and bills only what has actually resulted. It is recomputed every time an order line reaches `RESULTED` through a result release and every time a specimen is rejected, and it writes the order's `invoiced_total_cents`, `hsa_applied_cents`, and `patient_due_cents`.

The invoice uses the same four-step arithmetic as the cart estimate of Section 3.3, but its input set is only the order lines whose `status` is `RESULTED` at the moment of recompute; lines in `REJECTED`, `CANCELLED`, `COLLECTED`, or `ORDERED` are excluded. Bundle substitution runs only over the billable resulted lines, so a bundle's flat `bundle_price_cents` applies only when all of its members are `RESULTED` — a partially-resulted bundle instead bills its resulted members individually at line price, using each line's `unit_list_price_cents` and `repeat_discount_applied`. The per-line repeat discount of 0.15 is rounded half-up per line and summed; the platform tier discount applies the 0.15 rate at a subtotal of at least 50000 cents and the 0.10 rate at a subtotal of at least 20000 cents, rounded half-up; and HSA funds are then applied. Because the bundle flat price requires every member to result and rejected or cancelled lines drop out, the chronological invoice can diverge from the cart estimate even for the same patient inputs.

HSA settlement follows a pinned evaluation order whose steps appear circular but are not. The platform-discounted total is computed first (the third step above). The HSA draw, `hsa_applied_cents`, is then the smaller of the patient's remaining `hsa_balance_cents` and that discounted total — and is zero unless the fund source is `HSA_FSA`. Finally `patient_due_cents` is the discounted total minus `hsa_applied_cents`. At capture, and only at capture, the patient's `hsa_balance_cents` is debited by the computed `hsa_applied_cents` exactly once.

### 3.7. Scheduling, Order Completion, Payment Capture, and Cancellation

A `Patient` books a PSC appointment for an order by naming the `order_id`, a `psc_location_code`, a `slot_start` and a `slot_end` (both ISO 8601 UTC, with `slot_end` treated as exclusive and `slot_start` as inclusive), and an optional `fasting_confirmed` attestation defaulting to false. The slot window must be valid — `slot_end` strictly after `slot_start`, or the booking is rejected with `ERR_INVALID_SLOT_WINDOW`. The new slot must not overlap an existing `BOOKED` or `CHECKED_IN` appointment at the same `psc_location_code` under half-open `[start, end)` semantics, so two appointments that merely touch at a boundary do not conflict; an overlap is rejected with `ERR_SLOT_OVERLAP`. If any of the order's line offerings has `requires_fasting` true, the appointment's `fasting_confirmed` must be true, or the booking is rejected with `ERR_FASTING_NOT_CONFIRMED`. A new appointment is minted in `status` `BOOKED`.

A `PhlebotomyTech` checks an appointment in, moving it from `BOOKED` to `CHECKED_IN`, which is what enables collection for that PSC order. Check-in re-validates the fasting attestation under the same `ERR_FASTING_NOT_CONFIRMED` rule (the fasting check runs only after the `BOOKED`-state check passes), and a check-in attempted on an appointment that is not `BOOKED` is rejected as an invalid transition with `ERR_APPOINTMENT_NOT_CHECKED_IN` (HTTP 409).

An order's fulfillment axis advances automatically as its lines resolve. The first collected line moves the order from `AWAITING_COLLECTION` to `IN_PROCESSING`. When a result release leaves some — but not all — non-cancelled lines `RESULTED`, the order moves from `IN_PROCESSING` to `PARTIALLY_RESULTED`. When every order line has reached a terminal state (`RESULTED`, `REJECTED`, or `CANCELLED`) and at least one is `RESULTED`, the order advances to `COMPLETED`, whether it arrives there from `PARTIALLY_RESULTED` or directly from `IN_PROCESSING` without an intermediate partial; reaching `COMPLETED` finalizes `invoiced_total_cents`, `hsa_applied_cents`, and `patient_due_cents` through the chronological invoice of Section 3.6.

Payment capture is a `Patient` action that moves the payment axis from `AUTHORIZED` to `CAPTURED`. It carries `expected_order_version` and is permitted only when the order's `fulfillment_status` is `COMPLETED` (else `ERR_ORDER_NOT_COMPLETE_FOR_CAPTURE`) and its `payment_status` is `AUTHORIZED` (else `ERR_PAYMENT_NOT_CAPTURABLE`); the version must match per Section 2.8 (else `ERR_STALE_ORDER_VERSION`). On capture the `Payment` status becomes `CAPTURED` and its `captured_amount_cents` is set to the order's final `patient_due_cents`. When the fund source is `HSA_FSA`, the patient's `hsa_balance_cents` is reduced by the order's `hsa_applied_cents` and the payment's `hsa_drawn_cents` records that same draw; should the required draw exceed the patient's available `hsa_balance_cents`, the capture is rejected with `ERR_INSUFFICIENT_HSA_FUNDS`. Capture increments `Order.version` by one.

Cancellation is also a `Patient` action, carrying `expected_order_version`. An order may be cancelled while its fulfillment is `AWAITING_COLLECTION`, `IN_PROCESSING`, or `PARTIALLY_RESULTED`, but only if no order line is `RESULTED`; a cancellation against an order whose fulfillment is outside those three states (for example `COMPLETED` or already `CANCELLED`), or against one that already has a resulted line, is rejected with `ERR_ORDER_HAS_RESULTED_LINES` (the fulfillment-state check is evaluated first, then the resulted-line check, and only then payment refundability), and a version mismatch is rejected with `ERR_STALE_ORDER_VERSION`. Cancellation drives a three-hop cascade: every non-terminal order line in `ORDERED` or `COLLECTED` moves to `CANCELLED` (hop 1); each cancelled line whose specimen is still non-terminal has that `Specimen` marked `REJECTED` (hop 2); any `BOOKED` appointment for the order is moved to `CANCELLED`; and the payment is refunded along the payment axis (hop 3). On the payment axis, an `AUTHORIZED` payment moves directly to `REFUNDED` with no HSA restore needed because no HSA debit ever occurred, while a `CAPTURED` payment moves to `REFUNDED` and its captured amount is refunded — and when the fund source is `HSA_FSA`, the patient's `hsa_balance_cents` is increased by the payment's `hsa_drawn_cents` so that HSA funds are conserved. A refund attempted when the payment is neither `AUTHORIZED` nor `CAPTURED` is rejected with `ERR_PAYMENT_NOT_REFUNDABLE`. Cancellation increments `Order.version` by one. The order's payment axis may also move from `AUTHORIZED` to `REFUNDED` automatically as part of a system cancellation while authorized.

### 3.8. Specimen Processing, Critical-Value Protocol, Result Release, and Telehealth Referral

A `LabTech` processes a collected specimen by entering an `analyzer_value`. Processing is permitted only on a specimen in `COLLECTED`; an attempt otherwise is rejected with `ERR_RESULT_NOT_PROCESSABLE`. Processing advances the specimen from `COLLECTED` to `IN_ANALYSIS` and mints a `LabResult` carrying the source `specimen_id`, and — carried through from the specimen and its order — the `order_line_id`, the `patient_id`, a snapshot `test_code`, and the entered `analyzer_value`. The newly minted result's `final_flag` is null (it is computed only at release) and its `critical_acknowledged` begins false. Because processing mints a stand-alone `LabResult`, it returns `201 Created` with the new `LabResult` in `data`. At this moment the result's `provisional_flag` is computed from the offering's bounds alone, with no history. With `v` standing for the entered `analyzer_value`: the flag is `CRITICAL` when a `critical_low` bound exists and `v` is at or below it, or a `critical_high` bound exists and `v` is at or above it; otherwise the flag is `ABNORMAL` when a `ref_low` bound exists and `v` is strictly below it, or a `ref_high` bound exists and `v` is strictly above it; otherwise the flag is `NORMAL`. The critical bounds are inclusive and the reference bounds are strict, so a value exactly equal to `ref_high` is `NORMAL`. A freshly minted result whose `provisional_flag` is `CRITICAL` is parked in `PENDING_CRITICAL_CALLBACK`; any other provisional flag leaves it in `PROCESSING`.

A specimen that is unusable — hemolyzed or insufficient — may be rejected by a `LabTech`. Rejection is permitted only when the order line is `COLLECTED` and its specimen is in `COLLECTED` or `IN_ANALYSIS`; otherwise it is rejected with `ERR_SPECIMEN_NOT_REJECTABLE`. A specimen rejection moves the `Specimen` to `REJECTED` and the order line from `COLLECTED` to `REJECTED`, excludes that line from the chronological invoice, recomputes the order's invoiced total, and bubbles the order's `fulfillment_status` per the cascade rule.

A `CRITICAL` provisional result must route through the callback protocol before it can be released. A `LabTech` acknowledges the critical-value callback, which sets `critical_acknowledged` to true; release is otherwise blocked. A result release moves the result to `RELEASED` and is permitted only when the result is in `PROCESSING` or `PENDING_CRITICAL_CALLBACK` (else `ERR_RESULT_NOT_RELEASABLE`), when a critical result has had `critical_acknowledged` set true (else `ERR_CRITICAL_CALLBACK_REQUIRED`), and when the releasing `X-User-ID` differs from the specimen's `collected_by_user_id` (else `ERR_SOD_COLLECTOR_CANNOT_RELEASE`).

At release the result's `final_flag` is computed by adding a delta-check to the provisional logic. The base flag is the same bounds-only flag computed at processing. The server then finds the patient's most-recent strictly-prior `RELEASED` result for the same `patient_id` and `test_code` — the one with the latest `created_at` that is still earlier than this result's `created_at`, or none if there is no such prior result. If a prior result exists and the absolute difference between this result's `analyzer_value` and the prior's `analyzer_value` is at least 50 analyzer units, the swing escalates the base flag one severity step — `NORMAL` becomes `ABNORMAL`, `ABNORMAL` becomes `CRITICAL`, and `CRITICAL` stays `CRITICAL`; otherwise `final_flag` equals the base flag. Because of this, the same `analyzer_value` that is `NORMAL` provisionally can become `ABNORMAL` finally once a large enough prior swing exists.

A successful release fires the full result cascade: the order line moves from `COLLECTED` to `RESULTED` and its `Specimen` moves to `RESULTED` (hop 1); the order's invoiced total is recomputed and its fulfillment axis bubbles to `PARTIALLY_RESULTED` or `COMPLETED` per the rules of Section 3.7 (hop 2); and if the `final_flag` is `ABNORMAL` or `CRITICAL` and the patient's `consent_share_results` is true, a `TelehealthReferral` is minted `OPEN` (hop 3). When consent is absent, hop 3 is skipped silently with no error.

A released result may be amended by a `LabTech` by submitting a replacement `analyzer_value`. Amendment is permitted only on a `RELEASED` result (else `ERR_RESULT_NOT_AMENDABLE`); it moves the result to `AMENDED`, replaces the `analyzer_value`, recomputes both `provisional_flag` and `final_flag`, and — if the recomputed `final_flag` is now `ABNORMAL` or `CRITICAL` and no non-`CLOSED` referral is currently open for the result — mints a referral, consent permitting. "Escalated" here means the recomputed `final_flag` is `ABNORMAL` or `CRITICAL`; the server does not compare it against the pre-amend flag. Amendment performs no order-line, specimen, fulfillment, or invoice cascade.

A telehealth referral carries the `lab_result_id` that drives it, the `patient_id` carried from that result, and a `referral_reason` that mirrors the result's `final_flag` as either `ABNORMAL` or `CRITICAL`. A referral is created either automatically by the release cascade or manually by a `LabTech` or `CatalogAdmin` against a released abnormal or critical result; for a manual creation the only enforced gate beyond resolving the named `lab_result_id` is consent — the server does not separately verify that the target result is `RELEASED` or that its flag is abnormal or critical, and the minted `referral_reason` simply mirrors the result's current `final_flag`. A manual creation against a patient lacking consent is rejected with `ERR_CONSENT_REQUIRED`. A referral begins `OPEN` and may be moved to `SCHEDULED`; the `schedule` action sets `status` to `SCHEDULED` unconditionally with no state precondition (no error is defined for it). Its terminal state is `CLOSED`, for which no endpoint is exposed.

### 3.9. Reserving Lab Analyzers

A `LabTech` reserves an analyzer run window by naming an `analyzer_code`, a `run_start`, a `run_end` (both ISO 8601 UTC, with `run_end` required strictly after `run_start`), and an optional `buffer_minutes` that defaults to 30. The run is minted in `status` `RESERVED`. Unlike appointment slots, analyzer runs enforce a mandatory cleaning-and-calibration buffer after `run_end`: a new run does not overlap a prior `RESERVED` run on the same `analyzer_code` only when the new run's `run_start` is at or after the prior run's `run_end` plus the prior run's `buffer_minutes`, or the prior run's `run_start` is at or after the new run's `run_end` plus the new run's `buffer_minutes`. In any other arrangement the two runs overlap and the reservation is rejected with `ERR_ANALYZER_RUN_OVERLAP` — so two runs that merely touch at a boundary still conflict, because the buffer gap is mandatory. Releasing a run moves it from `RESERVED` to `RELEASED`, freeing the slot so it no longer participates in overlap checks; a release attempted when the run is not `RESERVED` is rejected with `ERR_ANALYZER_RUN_NOT_RELEASABLE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource, including the action endpoints that drive state transitions, return a `200 OK` status code. The two action endpoints that both transition a resource and mint a new stand-alone resource — `order-lines/{id}/collect` (mints a `Specimen`) and `specimens/{id}/process` (mints a `LabResult`) — follow the creation rule: each returns `201 Created` with the newly minted resource in `data`. The manual `telehealth-referrals` creation likewise returns `201`. All other action endpoints (archive, decision, resubmit, check-in, reject, acknowledge-critical, release, amend, schedule, analyzer-run release, capture-payment, cancel, and the clock-set) return `200 OK`. The complete request and response shape for each endpoint must be reconstructed from the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catalog/test-offerings` | Create a test offering | CatalogAdmin |
| GET | `/catalog/test-offerings` | List test offerings (paginated; archived included only with include_archived) | CatalogAdmin, Patient, LabTech, PhlebotomyTech, OrderingPhysician |
| GET | `/catalog/test-offerings/{id}` | Get one offering | CatalogAdmin, Patient, LabTech, PhlebotomyTech, OrderingPhysician |
| POST | `/catalog/test-offerings/{id}/archive` | Soft-delete (archive) an offering | CatalogAdmin |
| POST | `/catalog/panel-bundles` | Create a panel bundle | CatalogAdmin |
| GET | `/catalog/panel-bundles` | List panel bundles | CatalogAdmin, Patient, LabTech, PhlebotomyTech, OrderingPhysician |
| GET | `/catalog/panel-bundles/{id}` | Get one bundle | CatalogAdmin, Patient |
| POST | `/catalog/patients` | Register a patient | CatalogAdmin, Patient |
| GET | `/catalog/patients/{id}` | Get a patient (self or admin) | CatalogAdmin, Patient |
| PATCH | `/catalog/patients/{id}` | Update patient consent / HSA balance | CatalogAdmin, Patient |
| POST | `/catalog/carts` | Open a new cart for a patient | Patient |
| GET | `/catalog/carts` | List carts (filterable by patient_id) | Patient, CatalogAdmin |
| GET | `/catalog/carts/{id}` | Get a cart with computed totals | Patient, CatalogAdmin |
| PATCH | `/catalog/carts/{id}` | Change cart fund_source (re-prices) | Patient |
| POST | `/catalog/cart-lines` | Add a line to an OPEN cart | Patient |
| GET | `/catalog/cart-lines` | List cart lines (filterable by cart_id, test_offering_id) | Patient, CatalogAdmin |
| GET | `/catalog/cart-lines/{id}` | Get one cart line | Patient, CatalogAdmin |
| DELETE | `/catalog/cart-lines/{id}` | Remove a line from an OPEN cart | Patient |
| POST | `/catalog/orders` | Place an order from a checked-out cart | Patient |
| GET | `/catalog/orders/{id}` | Get an order with both status axes and totals | Patient, CatalogAdmin, LabTech, PhlebotomyTech |
| GET | `/catalog/orders` | List orders (filterable by patient_id, cart_id) | Patient, CatalogAdmin, LabTech |
| POST | `/catalog/orders/{id}/capture-payment` | Capture payment on a COMPLETED order | Patient |
| POST | `/catalog/orders/{id}/cancel` | Cancel an order (no resulted lines), refunding/compensating | Patient |
| GET | `/catalog/order-lines` | List order lines (filterable by order_id, test_offering_id) | Patient, CatalogAdmin, LabTech, PhlebotomyTech |
| GET | `/catalog/order-lines/{id}` | Get one order line | Patient, CatalogAdmin, LabTech, PhlebotomyTech |
| POST | `/catalog/order-lines/{id}/collect` | Collect a specimen for an order line | PhlebotomyTech |
| GET | `/catalog/physician-orders` | List physician orders (filterable by order_line_id, patient_id, status) | OrderingPhysician, Patient, CatalogAdmin |
| GET | `/catalog/physician-orders/{id}` | Get a physician order | OrderingPhysician, Patient, CatalogAdmin |
| POST | `/catalog/physician-orders/{id}/decision` | Physician review decision | OrderingPhysician |
| POST | `/catalog/physician-orders/{id}/resubmit` | Patient resubmits a NEEDS_MORE_INFO order | Patient |
| POST | `/catalog/appointments` | Book a PSC appointment for an order | Patient |
| GET | `/catalog/appointments` | List appointments (filterable by order_id, psc_location_code) | Patient, CatalogAdmin, PhlebotomyTech |
| GET | `/catalog/appointments/{id}` | Get one appointment | Patient, CatalogAdmin, PhlebotomyTech |
| POST | `/catalog/appointments/{id}/check-in` | Check in a booked appointment | PhlebotomyTech |
| POST | `/catalog/home-kits` | Mint/ship a home kit for a HOME_KIT order | CatalogAdmin, Patient |
| GET | `/catalog/home-kits` | List home kits (filterable by order_id) | Patient, CatalogAdmin |
| GET | `/catalog/home-kits/{id}` | Get one home kit | Patient, CatalogAdmin |
| GET | `/catalog/specimens` | List specimens (filterable by order_line_id) | LabTech, PhlebotomyTech, CatalogAdmin, Patient |
| GET | `/catalog/specimens/{id}` | Get one specimen | LabTech, PhlebotomyTech, CatalogAdmin, Patient |
| POST | `/catalog/specimens/{id}/process` | Enter analyzer value; mints a LabResult | LabTech |
| POST | `/catalog/specimens/{id}/reject` | Reject an unusable specimen | LabTech |
| GET | `/catalog/lab-results` | List lab results (filterable by specimen_id, order_line_id, patient_id) | LabTech, CatalogAdmin, Patient |
| GET | `/catalog/lab-results/{id}` | Get one lab result | LabTech, CatalogAdmin, Patient |
| POST | `/catalog/lab-results/{id}/acknowledge-critical` | Log the critical-value callback | LabTech |
| POST | `/catalog/lab-results/{id}/release` | Release a result (SoD + critical-callback gated) | LabTech |
| POST | `/catalog/lab-results/{id}/amend` | Amend a released result | LabTech |
| POST | `/catalog/telehealth-referrals` | Manually create a referral from a released result | LabTech, CatalogAdmin |
| GET | `/catalog/telehealth-referrals` | List referrals (filterable by lab_result_id, patient_id) | LabTech, CatalogAdmin, Patient |
| GET | `/catalog/telehealth-referrals/{id}` | Get one telehealth referral | LabTech, CatalogAdmin, Patient |
| POST | `/catalog/telehealth-referrals/{id}/schedule` | Move a referral to SCHEDULED | Patient, CatalogAdmin |
| POST | `/catalog/analyzer-runs` | Reserve an analyzer run window | LabTech |
| GET | `/catalog/analyzer-runs` | List analyzer runs (filterable by analyzer_code) | LabTech, CatalogAdmin |
| POST | `/catalog/analyzer-runs/{id}/release` | Release an analyzer reservation | LabTech |
| GET | `/catalog/payments` | List payments (filterable by order_id) | Patient, CatalogAdmin |
| GET | `/catalog/payments/{id}` | Get one payment | Patient, CatalogAdmin |
| POST | `/catalog/_clock/set_current_utc` | Set the logical clock | CatalogAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_INVALID_BUNDLE_MEMBERS` | 422 Unprocessable Entity |
| `ERR_OFFERING_NOT_ADDABLE` | 409 Conflict |
| `ERR_EMPTY_CART` | 409 Conflict |
| `ERR_STALE_CART_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_LINE_NOT_COLLECTIBLE` | 409 Conflict |
| `ERR_ORDER_NOT_COLLECTABLE_STATE` | 409 Conflict |
| `ERR_PHYSICIAN_ORDER_REQUIRED` | 409 Conflict |
| `ERR_PHYSICIAN_ORDER_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_PHYSICIAN_ORDER_NOT_RESUBMITTABLE` | 409 Conflict |
| `ERR_PWN_STATE_UNLICENSED` | 409 Conflict |
| `ERR_PWN_AGE_INELIGIBLE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_INVALID_SLOT_WINDOW` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_ANALYZER_RUN_OVERLAP` | 409 Conflict |
| `ERR_ANALYZER_RUN_NOT_RELEASABLE` | 409 Conflict |
| `ERR_FASTING_NOT_CONFIRMED` | 409 Conflict |
| `ERR_HOME_KIT_STATE_BANNED` | 409 Conflict |
| `ERR_SPECIMEN_NOT_REJECTABLE` | 409 Conflict |
| `ERR_RESULT_NOT_RELEASABLE` | 409 Conflict |
| `ERR_CRITICAL_CALLBACK_REQUIRED` | 409 Conflict |
| `ERR_SOD_COLLECTOR_CANNOT_RELEASE` | 403 Forbidden |
| `ERR_RESULT_NOT_AMENDABLE` | 409 Conflict |
| `ERR_CONSENT_REQUIRED` | 403 Forbidden |
| `ERR_ORDER_HAS_RESULTED_LINES` | 409 Conflict |
| `ERR_ORDER_NOT_COMPLETE_FOR_CAPTURE` | 409 Conflict |
| `ERR_PAYMENT_NOT_CAPTURABLE` | 409 Conflict |
| `ERR_PAYMENT_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_HSA_FUNDS` | 402 Payment Required |
| `ERR_RESULT_NOT_PROCESSABLE` | 409 Conflict |
