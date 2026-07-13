# Optical Retail & Eyewear API — Product Requirements Document

## 1. Introduction

Selling prescription eyewear is not selling a product; it is orchestrating a medical document, a physical catalog, an optical laboratory, an insurance payer, and a retail store into a single purchase that must be right the first time. A customer photographs a paper prescription, borrows five sample frames for a week, picks one, discovers their plan covers part of the frame but not the anti-reflective coating, pays the balance from a flexible-spending account, waits for a lab to grind and inspect the lenses, collects them at a store, and — three months later — snaps a temple arm and asks for a remake. Every one of those steps mutates money, inventory, or clinical safety, and every one of them can fail.

This document specifies the Optical Retail & Eyewear API, the backend that governs that entire arc. It is mounted under `/optical`. The API is deliberately opinionated about three things. First, **clinical safety**: a prescription is only actionable once a licensed optician has verified it, and lens material must be physically capable of carrying the correction the prescription demands. Second, **money conservation**: insurance benefit dollars and try-on sample units are conserved quantities, and every reservation the system takes must be released by an exactly equal compensating credit — no drift is tolerated. Third, **deterministic time**: the system runs on a logical clock that the operator advances explicitly, so that expiry and lateness are reproducible rather than incidental.

The reader should treat §2 as the invariant contract and §3 as the domain narrative. Where the two overlap, they reinforce rather than contradict each other.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. Six roles exist, and their names are spelled exactly as follows: `Customer`, `OpticianVerifier`, `StoreAssociate`, `LabTechnician`, `BenefitsAdmin`, and `PlatformAdmin`. A request that omits either header, or that presents an `X-User-Role` value outside those six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is well-authenticated but whose role does not appear in the authorized-role list for the endpoint it targets is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The `Customer` role is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a `Customer` compare that resource's customer foreign-key field to `X-User-ID`. Concretely, a `Customer` may only read or mutate prescriptions, home try-on kits, orders, warranty claims and exam appointments whose `customer_id` equals their own `X-User-ID`. The same rule applies to the `Customer` record itself: a `Customer` reading `/optical/customers/{id}` may only read the record whose `id` is their own `X-User-ID`. Resources that carry no customer foreign key — insurance policies, lab orders and insurance claims — carry no ownership check at all, so a `Customer` whose role appears in the endpoint's authorized-role list may read any of them. A violation of that ownership rule is also reported as `ERR_UNAUTHORIZED` (HTTP 403) — the API does not distinguish "not yours" from "not allowed", to avoid leaking the existence of other customers' records.

The other five roles are operator roles with opaque identity. When `X-User-Role` is `OpticianVerifier`, `StoreAssociate`, `LabTechnician`, `BenefitsAdmin`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to an entity's `id`. The server may nevertheless record it: when an `OpticianVerifier` verifies a prescription, the acting `X-User-ID` is written to that prescription's `verified_by` field. No such recording happens for the remaining four operator roles.

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

List endpoints accept two query-string parameters. `limit` bounds the number of items returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of items skipped before the window begins; when omitted it defaults to 0. A `limit` or `offset` that is not parseable as an integer, or that falls outside those bounds, is refused with `ERR_INVALID_REQUEST` (HTTP 400) rather than clamped.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order — in practice, in server insertion order, which is what breaks ties between resources created within the same millisecond. Every filter a list endpoint declares is an exact-equality match on the named field, and an omitted or empty filter is simply not applied.

List responses expose four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id`: a UUID string with no type prefix of any kind. Clients never supply an `id`; they receive one.

Most resources — insurance policies, stores, frames, lens options, customers, prescriptions, home try-on kits, exam appointments, orders, lab orders, insurance claims and warranty claims — additionally carry three system-managed fields:

- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first written.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations the resource did not ask for (a cascade from a parent counts).
- `version` — an integer that increments by exactly one on every mutation of the resource, whether that mutation was a direct client write or a side effect propagated from elsewhere. A freshly created resource is minted at `version` 1.

These two system stamps, and the envelope's `api_request_timestamp`, are minted from the server's real wall-clock time, **not** from the logical clock of §2.5. The logical clock governs comparisons and the one field that is explicitly stamped from it, a lab order's `delivered_at`; it never governs `created_at` or `updated_at`. Client-supplied instants, by contrast — `plan_year_start`, `dob`, `issued_at`, `expires_at`, `ship_date`, `due_date`, `start_at`, `end_at` — are parsed for comparison but stored and echoed back **verbatim**, exactly as the client wrote them; the server does not re-format or normalise them.

There is one deliberate exception. A try-on kit item — the row that records "sample unit of frame X is currently in kit Y" — carries only `id` and `created_at`. It has **no** `updated_at` field and **no** `version` field, and clients must not expect either to be present in its representation.

Derived money and score fields are not exempt from versioning. When a policy's remaining allowance moves, when a customer's risk score is recomputed, when an order's customer-due amount is re-quoted, that is a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments. A *mutation*, however, means a change: a re-statement that leaves every field exactly as it was is not one, and it neither refreshes `updated_at` nor increments `version`. Concretely, a ledger move of zero cents (crediting or debiting a policy's `frame_allowance_remaining_cents` by 0, debiting or crediting a customer's `fsa_balance_cents` by 0, adding zero to a policy's `annual_reimbursed_cents`) leaves that policy or customer entirely untouched, and a risk-score recomputation that lands on the same `return_risk_score` and the same `lifetime_kit_count` the customer already carried leaves the customer entirely untouched.

### 2.5. The Logical Clock

The server does not read wall-clock time. It reads a **logical clock** whose value, before any client has touched it, is exactly `2026-05-01T00:00:00Z`. Every temporal comparison in this specification — prescription expiry, kit lateness, warranty age, the rolling-window cutoff for return risk — is made against that logical clock, and the logical clock never falls back to real time.

A `PlatformAdmin` moves the clock by supplying a `to_iso8601` instant to the clock-setting capability described in §4; any parseable ISO 8601 instant is accepted, including one earlier than the clock's current value, and the server imposes no monotonicity constraint. The call returns 200 with a `data` object holding exactly three fields: the new `current_utc` (an ISO 8601 UTC timestamp with three fractional digits), plus two lists that name every resource this particular move re-stated — `expired_prescription_ids` and `overdue_kit_ids`. A move that re-states nothing returns two empty lists.

Advancing the clock is the **only** way two state transitions in this system ever fire. First, every `VERIFIED` prescription whose `expires_at` is at or before the new clock value transitions to `EXPIRED`, incrementing that prescription's `version`. Second, every `SHIPPED` home try-on kit whose `due_date` is strictly before the new clock value transitions to `OVERDUE`, latches `was_overdue` to true, increments its own `version`, and triggers a recomputation of its owning customer's `return_risk_score`. Nothing else in the system produces an `EXPIRED` prescription or an `OVERDUE` kit.

### 2.6. Money, Counts, and Rounding Discipline

Every monetary amount in this system is an **integer number of cents**. There are no decimal currency values anywhere in a request body or a response body; a frame that retails for three hundred dollars has a `price_cents` of `30000`. Percentages and refractive indices are the only non-integer numeric inputs, and they are never money.

Because every price is an integer, every arithmetic step that could produce a fraction names its rounding mode explicitly, and the mode differs by step. Three conventions are in play across the system, and they are not interchangeable:

- **Floor** — truncation toward zero of a non-negative product. Every percentage applied to money floors: the coating bundle discount, the order-level volume discount, the frame line's proportional share of that discount, and the customer's share of a remake.
- **Round half up** — a value of exactly one half rounds away from zero. This governs the high-power lens surcharge, each individual out-of-network service-line reimbursement, and the final return-risk percentage.
- **Ceiling** — rounding up to the next whole unit. This governs only the day count used for a late try-on kit.

Where an amount is both rounded and clamped, the rounding happens first and the clamp second. Where an aggregate is both rounded and summed, §3.8 pins the order explicitly, because the two orders produce different totals.

### 2.7. Optimistic Concurrency on Parent Versions

Two write endpoints in this system legitimately supersede an existing child of a parent resource, which means a state precondition alone cannot protect them: the second write is, by the product's own semantics, a valid operation. Those two writes are therefore guarded by optimistic concurrency control against the parent's `version`.

Filing an insurance claim — `POST /optical/insurance-claims` — requires a non-optional `expected_order_version` field in the request body, carrying the `version` of the target `Order` as the client last observed it. If that value does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The purpose is precise: a new claim voids the order's existing active claim and re-reserves frame benefit against the policy, so the client must not be permitted to file against money fields it has not seen.

Filing a warranty claim — `POST /optical/warranty-claims` — requires a non-optional `expected_lab_order_version` field in the request body, carrying the `version` of the target `LabOrder` as the client last observed it. If that value does not equal the lab order's current `version`, the request is rejected with `ERR_STALE_LAB_ORDER_VERSION` (HTTP 412). Again the reason is that a second warranty filing would otherwise succeed under the product's supersede semantics; the version check pins the filing to the lab order the client actually read.

No other endpoint in this API accepts a version field. Clients must not send one, and the server must not require one.

### 2.8. Cascades and Conserved Quantities

Several operations in this system mutate more than one resource. When they do, the cascade is deterministic, fully specified in §3, and — critically — **conservative**: it never creates or destroys a unit of a conserved quantity.

Two quantities are conserved. The first is **frame-allowance dollars on an insurance policy**. For any policy, the policy's `frame_allowance_remaining_cents` plus the sum of `reserved_frame_benefit_cents` across every non-`VOID` claim against that policy always equals the policy's `frame_allowance_cents`. Confirming an order is the forward action that reserves benefit; cancelling the order is the compensating action that voids the claim and credits back the exact amount it had reserved — not a recomputed amount, the reserved amount.

The second is **physical try-on sample units of a frame**. For any frame, the frame's `tryon_available` plus the count of try-on kit items on that frame whose `outcome` is still `PENDING` always equals the frame's `tryon_stock`. Requesting a kit is the forward action that mints one `PENDING` item per frame and decrements availability; returning the kit is the compensating action that resolves every `PENDING` item and increments availability by exactly one per resolved item — regardless of whether the item resolved to `KEPT` or to `RETURNED`, because both outcomes physically release the sample.

Cascades also propagate state upward. A lab order is a child of an order, and the lab order's production transitions drive the parent order's fulfillment dimension; the parent's `version` increments on each such bubble-up exactly as if the parent had been written directly.

### 2.9. Validation Order

When a single request violates more than one rule, exactly one error is returned, and which one is not a matter of implementation taste. The system evaluates checks in the following fixed priority order and reports the **first** failure it encounters; later checks are never reached.

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Endpoint authorization.** The acting role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Request schema.** Required fields present, types correct, enum members valid, money and count fields not negative, `expires_at` strictly after `issued_at`, `due_date` strictly after `ship_date`, `end_at` strictly after `start_at` — otherwise `ERR_INVALID_REQUEST` (400). Applies to every write.
4. **Path existence.** Every resource named in the URL path exists, validated left to right, so that the leftmost missing identifier is the one reported. The not-found codes are `ERR_CUSTOMER_NOT_FOUND`, `ERR_FRAME_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND` and `ERR_APPOINTMENT_NOT_FOUND`, all HTTP 404.
5. **Body reference existence.** Every resource id referenced in the request body exists; the codes are `ERR_CUSTOMER_NOT_FOUND`, `ERR_FRAME_NOT_FOUND`, `ERR_LENS_OPTION_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND` and `ERR_APPOINTMENT_NOT_FOUND`, all HTTP 404. A lens option whose `status` is `RETIRED` is treated as **not found** at this step, as is a lens option referenced in the wrong slot (a coating supplied where a material was expected, or the reverse) — both surface as `ERR_LENS_OPTION_NOT_FOUND`.
6. **Customer ownership.** When the acting role is `Customer`, `X-User-ID` equals the `customer_id` of the resource being read or mutated — otherwise `ERR_UNAUTHORIZED` (403). Applies to every `Customer`-role operation on prescriptions, kits, orders, warranty claims and appointments.
7. **Stale order version** — `expected_order_version` equals the order's current `version`, otherwise `ERR_STALE_ORDER_VERSION` (412). Applies only to insurance-claim creation.
8. **Stale lab-order version** — `expected_lab_order_version` equals the lab order's current `version`, otherwise `ERR_STALE_LAB_ORDER_VERSION` (412). Applies only to warranty-claim creation.
9. **From-state.** The target entity sits in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every state-transition endpoint.
10. **Prescription verified at confirmation** — otherwise `ERR_PRESCRIPTION_NOT_VERIFIED` (409). Applies only to order confirmation.
11. **Lab order delivered** — a warranty claim may only be filed against a lab order whose `status` is `DELIVERED` and whose `delivered_at` is therefore non-null; otherwise `ERR_LAB_ORDER_NOT_DELIVERED` (409). Applies only to warranty-claim creation.
12. **Store open** — otherwise `ERR_STORE_CLOSED` (409). This check guards exactly two operations: confirming a `BOPIS` order, and shipping a lab order whose parent order is `BOPIS`.
13. **Pupillary distance in range** — otherwise `ERR_PD_OUT_OF_RANGE` (422). This check guards exactly three operations: prescription capture, prescription resubmission, and order creation.
14. **Lens material strong enough for the correction** — otherwise `ERR_LENS_INCOMPATIBLE_WITH_RX` (422). Order creation only.
15. **Coating compatibility** — otherwise `ERR_COATING_INCOMPATIBLE` (422). Order creation only.
16. **Frame is orderable** — otherwise `ERR_FRAME_DISCONTINUED` (422). Order creation only.
17. **Prescription ownership** — the referenced prescription's `customer_id` matches the order's or the appointment's `customer_id`; otherwise `ERR_PRESCRIPTION_OWNER_MISMATCH` (422). This check guards exactly two operations: order creation and exam completion.
18. **Prescription not expired** — otherwise `ERR_PRESCRIPTION_EXPIRED` (422). This check guards exactly two operations: prescription verification and order confirmation.
19. **Warranty window** — otherwise `ERR_WARRANTY_EXPIRED` (422). Warranty-claim creation only.
20. **Kit not empty** — otherwise `ERR_KIT_EMPTY` (422). Kit request only.
21. **Kit not oversized** — otherwise `ERR_KIT_SIZE_EXCEEDED` (422). Kit request only.
22. **Return-risk gate** — otherwise `ERR_CUSTOMER_TRYON_BLOCKED` (403). Kit request only.
23. **Kit window non-overlapping** — otherwise `ERR_TRYON_WINDOW_CONFLICT` (409). Kit request only.
24. **Sample units available** — otherwise `ERR_TRYON_STOCK_UNAVAILABLE` (409). Kit request only.
25. **Exam chair available** — otherwise `ERR_EXAM_SLOT_CONFLICT` (409). Exam booking only.
26. **Delivery method consistency** — otherwise `ERR_BOPIS_STORE_REQUIRED` (422). Order creation only.
27. **Remake limit** — otherwise `ERR_REMAKE_LIMIT_EXCEEDED` (409). Lab QC only.
28. **Benefit sufficiency** — otherwise `ERR_INSUFFICIENT_BENEFIT` (422). Order confirmation only.
29. **FSA sufficiency** — otherwise `ERR_INSUFFICIENT_FSA` (422). Order confirmation only.
30. **Annual reimbursement headroom** — otherwise `ERR_ANNUAL_MAX_EXCEEDED` (422). Claim reimbursement only.

The four kit-request checks in positions 20–24 are the clearest illustration of why ordering matters: a blocked customer requesting six frames over a conflicting window receives `ERR_KIT_SIZE_EXCEEDED`, not `ERR_CUSTOMER_TRYON_BLOCKED`, because the size check sits above the risk gate.

Nested reads follow the same left-to-right discipline. A request for the prescriptions belonging to a customer that does not exist fails with `ERR_CUSTOMER_NOT_FOUND` before the server ever considers the prescription collection; a request for the items of a kit that does not exist fails with `ERR_KIT_NOT_FOUND`.

### 2.10. Interval Semantics: Two Conventions, Deliberately Opposite

The system schedules two very different things over time, and it uses two different interval conventions to do it. Implementers must not unify them.

**Exam chairs at a store use half-open intervals with a trailing buffer.** An exam occupies the span from `start_at` inclusive to `end_at` exclusive, and every store appends a turnover buffer of `buffer_minutes` **after** the interval, extending it. Two exams collide when the span from a candidate's `start_at` up to (but not including) its `end_at` plus buffer intersects the corresponding buffered span of an existing appointment. The consequence is worth stating plainly: two back-to-back exams separated by a gap of strictly less than `buffer_minutes` collide, and two exams separated by a gap of exactly `buffer_minutes` do **not** collide. A store tolerates collisions up to its capacity; a booking is refused with `ERR_EXAM_SLOT_CONFLICT` only when the number of colliding appointments (counting both `BOOKED` and `COMPLETED` ones) is already greater than or equal to `exam_chairs`.

**Customer try-on windows use closed intervals with a capacity of one.** A kit occupies the span from `ship_date` through `due_date`, with **both** endpoints inclusive. Two of the same customer's windows therefore collide even when they merely touch: if one kit's `due_date` falls on the same instant as another kit's `ship_date`, that is an overlap, and the second request is refused with `ERR_TRYON_WINDOW_CONFLICT`. This is the exact opposite of the exam-chair convention, where touching intervals are disjoint. The candidate set for the collision check is the customer's own kits whose `status` is `REQUESTED`, `SHIPPED`, or `OVERDUE`; a `RETURNED` kit no longer occupies a window. Capacity is one — a customer may hold at most one live kit window at a time.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Catalog, the Store Network, and the Customer Book

Before anything can be sold, a `PlatformAdmin` populates four catalogs.

A **vision plan** is registered with the insurer-side `member_id`, a `network` designation that is either `IN_NETWORK` (the plan pays the retailer directly at point of sale) or `OUT_OF_NETWORK` (the plan reimburses the member afterwards), a `frame_allowance_cents` figure covering the plan year's frame dollars, a flat `lens_copay_cents` that the member owes on the lens portion of an in-network order, an `annual_max_cents` ceiling on out-of-network reimbursement for the year, and a `plan_year_start` instant in ISO 8601 UTC. Two further inputs are optional. `oon_reimburse_pct` is the fraction of the eligible amount that an out-of-network plan reimburses per service line; it lies between 0 and 1 inclusive and defaults to `0.75` when omitted. `oon_fee_schedule` is a map from service code to the maximum eligible amount in cents for that code — for instance a schedule that allows five thousand cents against code `92004` — and it defaults to an empty map; **a code absent from the map is eligible for zero cents**, which means an out-of-network claim filed against an empty schedule reimburses nothing at all. Every money input on a plan must be zero or greater. At registration the plan's two ledgers are seeded: `frame_allowance_remaining_cents` starts equal to `frame_allowance_cents`, and `annual_reimbursed_cents` starts at zero. Reading a policy returns both live ledgers.

A **store** is registered with a `name`, a `status` of either `OPEN` or `CLOSED` (defaulting to `OPEN`), an `exam_chairs` count of at least one that caps concurrent exam intervals, a `buffer_minutes` turnover figure of zero or more that defaults to ten, and a `pickup_capacity_per_day` figure that defaults to fifty. That last figure is informational only — it is stored and returned, and the system never enforces it.

A **frame** is registered with a unique catalog `sku`, a model `name`, a `brand`, a `price_cents` retail price of zero or more, a `status` of `ACTIVE` or `DISCONTINUED` (defaulting to `ACTIVE`), a `tryon_stock` count of zero or more physical sample units held for home try-on, and the two geometry bounds `min_pd_mm` and `max_pd_mm` that describe the narrowest and widest pupillary distance the frame can glaze. At registration, `tryon_available` is seeded equal to `tryon_stock`. `ACTIVE` frames may be ordered and tried on; `DISCONTINUED` frames may not be ordered.

A **lens option** is registered with a unique short `code` (for example `M167`, `AR`, `BLUE`, `PHOTO`), a `category` of either `MATERIAL` or `COATING`, a `base_price_cents` list price of zero or more, and a `status` of `ACTIVE` or `RETIRED` (defaulting to `ACTIVE`). A `MATERIAL` option carries a `material_index` refractive index — one of `1.50`, `1.60`, `1.67`, `1.74` — while a `COATING` option leaves `material_index` null, which is its default. That four-value enumeration is descriptive rather than enforced: `material_index` is an optional numeric input on any option, the server accepts any number there and rejects nothing, and a `MATERIAL` registered with a null `material_index` is simply never strong enough for any correction — every order naming it is refused with `ERR_LENS_INCOMPATIBLE_WITH_RX`. Any option may declare an `incompatible_with` array holding the `code` values of other options it must not share an order with; the default is an empty array. A `RETIRED` option can never be selected on a new order.

The words "unique" above — a frame's `sku`, a lens option's `code`, a customer's `email` — describe a catalog convention that the operator is expected to honour, not a constraint the server enforces. The API does not reject a registration that duplicates an existing `sku`, `code` or `email`; there is no uniqueness-violation error in the catalogue of §5.

A **customer** is registered with a `full_name`, a unique `email`, a `dob` date of birth in ISO 8601 UTC, an optional `insurance_policy_id` pointing at a registered plan (null by default — the customer is then self-pay), and an optional `fsa_balance_cents` flexible-spending balance of zero or more that defaults to zero. Two computed fields are seeded at registration: `lifetime_kit_count` at zero and `return_risk_score` at zero. Customers may be listed and filtered by the `insurance_policy_id` they are enrolled in.

### 3.2. Capturing a Prescription, Verifying It, and the Rejection Loop

A prescription enters the system either from the customer themselves or from a `StoreAssociate` working the retail floor, and it always begins in `SUBMITTED`. The payload names the `customer_id` it belongs to, the four measurement powers — `od_sphere` and `od_cylinder` for the right eye, `os_sphere` and `os_cylinder` for the left — the `pd_mm` pupillary distance, the `issued_at` date the prescription was written and the `expires_at` date it lapses, which must be strictly after `issued_at`. An optional `prism_diopters` correction defaults to `0.0` and may not be negative. The `pd_mm` value must be at least 45.0 millimetres and at most 80.0 millimetres; anything outside that closed range is refused with `ERR_PD_OUT_OF_RANGE`. At capture, `resubmit_count` is seeded at zero, `verified_by` and `rejection_reason` are both null.

An `OpticianVerifier` then rules on a `SUBMITTED` prescription by supplying a `decision`. A decision of `VERIFIED` advances the prescription `SUBMITTED → VERIFIED`, but only if the prescription's `expires_at` is strictly after the logical clock at the moment of the ruling — an optician cannot bless a lapsed prescription, and the attempt is refused with `ERR_PRESCRIPTION_EXPIRED`. On verification, the acting optician's `X-User-ID` is written into `verified_by`, `rejection_reason` is cleared to null, and the prescription's `version` increments.

A decision of `REJECTED` advances the prescription `SUBMITTED → REJECTED` and requires a `rejection_reason`; a rejection without one is refused with `ERR_INVALID_REQUEST`. The supplied text is written to `rejection_reason` and the `version` increments. `verified_by` remains null.

Rejection is not terminal — it is a loop. The owning customer, and only the owning customer, may correct a `REJECTED` prescription and resubmit it, driving it `REJECTED → SUBMITTED`. Resubmission overwrites **all** the measurement fields from the payload (`od_sphere`, `od_cylinder`, `os_sphere`, `os_cylinder`, `pd_mm`, `issued_at`, `expires_at`, and the optional `prism_diopters`), increments `resubmit_count` by one, clears `rejection_reason` back to null, and increments `version`. The resubmitted `pd_mm` is subject to the same 45.0-to-80.0 closed range and the same `ERR_PD_OUT_OF_RANGE` refusal. A prescription may cycle `REJECTED → SUBMITTED → REJECTED` indefinitely; there is no cap on `resubmit_count`.

The one terminal state is `EXPIRED`, and only the logical clock produces it: a `VERIFIED` prescription whose `expires_at` is at or before a newly-set clock value transitions `VERIFIED → EXPIRED` and its `version` increments. An `EXPIRED` prescription can be neither verified nor resubmitted, and a draft order that references it can no longer be confirmed. Prescriptions may be read individually, and listed per customer with an optional `status` filter.

### 3.3. Eye Exams and the Prescription They Produce

A customer books an eye exam at a store by naming the `customer_id`, the `store_id`, and the `start_at` / `end_at` bounds of the slot, where `end_at` must be strictly after `start_at`. The appointment is created in `BOOKED`, with `resulting_prescription_id` null. Booking is refused with `ERR_EXAM_SLOT_CONFLICT` when the store's chairs are already fully committed over the requested span under the buffered half-open arithmetic of §2.10.

A `StoreAssociate` closes the exam by completing it, which advances the appointment `BOOKED → COMPLETED` and links the prescription the exam produced: the payload carries a `prescription_id`, which is written to `resulting_prescription_id`, and the appointment's `version` increments. The link is not free — the referenced prescription must belong to the same person as the appointment, and a prescription whose `customer_id` differs from the appointment's `customer_id` is refused with `ERR_PRESCRIPTION_OWNER_MISMATCH`.

Appointments may be read individually and listed with filters on `customer_id`, `store_id`, `resulting_prescription_id`, and `status`.

### 3.4. Home Try-On: Holding Samples, Returning Them, and Earning a Risk Score

Home try-on is the system's inventory problem. A customer requests a kit by naming their `customer_id`, an array of `frame_ids`, and the closed window over which they will hold the samples — `ship_date` through `due_date`, with `due_date` strictly after `ship_date`. The kit is created in `REQUESTED` with `was_overdue` false, `kept_count` zero, `late_fee_cents` zero, and `item_count` set to the number of frames requested.

Four business gates guard the request, and §2.9 fixes the order in which they fire. The `frame_ids` array must be non-empty, or the request is refused with `ERR_KIT_EMPTY`. It must name at most five **distinct** frames, or the request is refused with `ERR_KIT_SIZE_EXCEEDED` — the size gate counts distinct ids, while `item_count` and the minting below count array entries, so a repeated id is legal and mints one item per occurrence. The requesting customer's `return_risk_score` must be **strictly below 70** — the gate fires at a score of exactly 70 and above, not merely above 70 — or the request is refused with `ERR_CUSTOMER_TRYON_BLOCKED`. The requested window must not intersect any live window of the same customer under the closed-interval, touching-counts-as-overlap rule of §2.10, or the request is refused with `ERR_TRYON_WINDOW_CONFLICT`. Finally, every requested frame must have at least one sample unit free — `tryon_available` of one or more — or the request is refused with `ERR_TRYON_STOCK_UNAVAILABLE`; that check fires at exactly zero and never at one.

A kit that survives all five gates mints one try-on kit item per named frame. Each item records its `kit_id`, its `frame_id`, and an `outcome` that starts at `PENDING`, and each item's creation decrements its frame's `tryon_available` by one. Those items are the physical hold, and they are readable both as the items of a kit and — filtered by `outcome` — as the items that hold a given frame.

A `StoreAssociate` ships the kit, advancing it `REQUESTED → SHIPPED` and incrementing its `version`. From there the kit can go one of two ways. If the clock passes `due_date` while the kit is still out, the kit transitions `SHIPPED → OVERDUE`, latches `was_overdue` to true forever (the flag survives the eventual return), increments its `version`, and forces a recomputation of the customer's `return_risk_score`.

Returning the kit is the customer's job, and it is permitted from `SHIPPED` or from `OVERDUE` — any other state is refused with `ERR_INVALID_STATE`. The return payload carries `kept_frame_ids`, the frames the customer intends to buy; the field is mandatory, and a return that omits it is refused with `ERR_INVALID_REQUEST` — a customer who keeps nothing sends an explicit empty array. Every id in that array must be the `frame_id` of an item actually on this kit; an id that is not is refused with `ERR_FRAME_NOT_FOUND`. The return then runs a three-link cascade. First, the kit moves to `RETURNED` and its `late_fee_cents` is computed. Second, every item on the kit still sitting at `PENDING` resolves: an item whose `frame_id` appears in `kept_frame_ids` resolves to `KEPT`, and every other pending item resolves to `RETURNED`. Third, every frame behind a resolved item has its `tryon_available` incremented by one — **both** resolutions release the physical hold, because a customer who "keeps" a sample in the try-on sense is expressing purchase intent, not walking off with the sample. The kit's `kept_count` becomes the number of items that resolved to `KEPT`, its `version` increments, and the customer's `lifetime_kit_count` and `return_risk_score` are recomputed.

**The late fee.** If the logical clock at the moment of return is at or before the kit's `due_date`, the fee is zero — a return on the due instant itself is on time. Otherwise the system takes the elapsed time from `due_date` to the clock, divides it by one day, and rounds **up** to a whole number of days late; a return one minute past the deadline is one day late. The fee is five hundred cents for each day late, and it is then clamped to a ceiling of five thousand cents — so a kit ten or more days late incurs the same fifty-dollar maximum as a kit a hundred days late.

**The return-risk score.** The score is an integer between 0 and 100 that measures how badly a customer treats borrowed samples, and it is recomputed on exactly two occasions: whenever a kit is returned, and whenever the clock flips a shipped kit to `OVERDUE`. The system first assembles the customer's **history**: every one of that customer's kits whose `status` is `RETURNED` or `OVERDUE`. Kits still sitting at `REQUESTED` or `SHIPPED` are excluded entirely — they have not yet told us anything. The size of that history is written to the customer's `lifetime_kit_count`.

The history then selects the scoring window, and the selection is pinned on `lifetime_kit_count`:

- **The ROLLING variant** applies when `lifetime_kit_count` is **fewer than three**. The customer has too little history for a lifetime average to be fair, so only recent kits count: the window holds exactly those history kits whose `due_date` falls on or after the instant 180 days before the current logical clock. Kits older than that window are invisible to both the numerator and the denominator.
- **The STRICT variant** applies when `lifetime_kit_count` is **three or more**. Enough history exists to average over the whole relationship, so the window holds **every** kit in the history regardless of `due_date`, and no cutoff is applied at all.

For an identical set of kits the two variants can diverge sharply, because an old, clean kit that the ROLLING window would discard still drags the STRICT average down — that divergence is intentional, and it is the reason the variant boundary sits at exactly three.

Once the window is chosen, the score follows. If the window is empty, the score is zero. Otherwise the system counts two things across the window: the number of kits whose `kept_count` is zero (the customer borrowed and bought nothing), and the number of kits whose `was_overdue` flag is true (the customer held the samples past the deadline). A kit can contribute to both counts. The zero-kept count is weighted at six tenths, the overdue count at four tenths; the two weighted counts are added, divided by the number of kits in the window, multiplied by one hundred, and the result is rounded half up to a whole integer. That integer is the customer's `return_risk_score`, and once it reaches 70 the customer is locked out of new kits until returns bring it back down.

### 3.5. Building an Order: Fit, Optics, and the Lens Upcharge

A customer builds an order in `DRAFT` by naming their `customer_id`, the `prescription_id` the glasses will be cut to, the `frame_id`, the `material_option_id` for the lens blank, and a `delivery_method` of either `SHIP` (the finished glasses are mailed) or `BOPIS` (they are routed to a store for pickup). Three inputs are optional: `coating_option_ids`, an array of coating options that defaults to empty; `store_id`, the pickup location; and `exam_appointment_id`, an optional back-link to the exam that produced the prescription. Delivery method and store must agree — `BOPIS` requires a non-null `store_id` and `SHIP` requires `store_id` to be null; either mismatch is refused with `ERR_BOPIS_STORE_REQUIRED`. The order is created with `fulfillment_status` of `DRAFT`, `payment_status` of `UNPAID`, `quote_variant` of `ESTIMATED`, `fsa_applied_cents` of zero and `active_claim_id` null.

Four safety checks stand between the payload and a persisted draft, and §2.9 fixes their order. The prescription's `pd_mm` must lie within the ordered frame's geometry — at least `min_pd_mm` and at most `max_pd_mm`, both bounds inclusive — or the order is refused with `ERR_PD_OUT_OF_RANGE`. The chosen material must be optically strong enough for the correction, or the order is refused with `ERR_LENS_INCOMPATIBLE_WITH_RX`. No two selected coatings may be mutually exclusive: if either coating names the other's `code` in its `incompatible_with` array, the pairing is refused with `ERR_COATING_INCOMPATIBLE` — the check is symmetric, so one-sided declarations still block. And the frame's `status` must be `ACTIVE`, or the order is refused with `ERR_FRAME_DISCONTINUED`. Separately, the prescription must belong to the ordering customer: a `customer_id` mismatch between the order and the prescription is refused with `ERR_PRESCRIPTION_OWNER_MISMATCH`.

**Deriving the correction's strength.** The system reduces the prescription to a single number it calls the prescription's power. It takes the larger of the absolute values of `od_sphere` and `os_sphere` — the stronger eye's sphere — and the larger of the absolute values of `od_cylinder` and `os_cylinder` — the stronger eye's cylinder. The power is the stronger sphere plus one half of the stronger cylinder.

That power selects the **required index tier**, which is the weakest refractive index the lens blank is allowed to have. A power below 4.00 requires a tier of `1.50`. A power of at least 4.00 but below 6.00 requires `1.60`. A power of at least 6.00 but below 8.00 requires `1.67`. A power of 8.00 or above requires `1.74`. If the selected material option's `material_index` is **below** the required tier, the order is refused with `ERR_LENS_INCOMPATIBLE_WITH_RX`; an index at or above the tier is accepted, and an over-specified blank is always permitted. This check runs before any money is computed.

**The lens upcharge.** Once the optics pass, the system computes `lens_upcharge_cents` in the following pinned order, in integer cents, and freezes it on the order. It is computed exactly once, at order creation, and no later operation ever recomputes it.

1. Start with the material's `base_price_cents`.
2. Add the **coating total**: the plain sum of `base_price_cents` across every selected coating. The order of the array does not affect the sum.
3. Subtract the **coating bundle discount**. When two or more coatings are selected, the discount is fifteen percent of the coating total, floored to whole cents. When fewer than two coatings are selected, the discount is zero — a single coating gets no bundle break.
4. Add the **prism surcharge**: forty-five dollars — 4,500 cents — whenever the prescription's `prism_diopters` is at least 0.50, and nothing at all when it is below 0.50.
5. Add the **high-power surcharge**. Subtract 6.00 from the prescription's power, multiply the remainder by one thousand cents per diopter, and round that product half up to whole cents; if the result is negative — which it is for any power below 6.00 — treat it as zero; then clamp it downward to a ceiling of sixty dollars, that is 6,000 cents. The clamp binds at any power of 12.00 or more.

The sum of those five terms is `lens_upcharge_cents`.

### 3.6. Confirming the Order: The Money Waterfall, FSA, and Cancellation

Money on an order is computed by a waterfall whose evaluation order is fixed and non-negotiable, because the discount tier is keyed on the pre-discount subtotal, the insurance benefit is keyed on the post-discount amounts, and the flexible-spending contribution is applied last against whatever the customer still owes. The waterfall runs first at order creation — where it produces the draft's `ESTIMATED` quote with no FSA contribution — and again at confirmation, re-read against the policy's live allowance and the customer's live balance.

**Step one: the subtotal.** `subtotal_cents` is the frame's `price_cents` plus the order's frozen `lens_upcharge_cents`.

**Step two: the volume discount.** The subtotal selects a discount rate. A `subtotal_cents` below 25,000 cents earns nothing. A subtotal of at least 25,000 cents but below 50,000 cents earns ten percent. A subtotal of 50,000 cents or more earns fifteen percent. `discount_cents` is that rate applied to `subtotal_cents` and floored to whole cents. The **net** amount is `subtotal_cents` minus `discount_cents`.

**Step three: splitting the discount across the two lines.** The frame line carries its own proportional share of the discount, so that a frame allowance is applied against the discounted frame rather than the list frame. The discounted frame amount is the frame's `price_cents` minus the discount rate applied to that `price_cents` and floored to whole cents. The discounted lens amount is whatever remains: the net amount minus the discounted frame amount. That residual definition matters — the two floorings are not independent, and the lens line absorbs the rounding remainder.

**Step four: the benefit waterfall.** If the customer has no `insurance_policy_id`, or if their policy's `network` is `OUT_OF_NETWORK`, then `benefit_frame_cents` and `benefit_lens_cents` are both zero: an out-of-network plan pays the member afterwards, never the retailer at the counter. For an `IN_NETWORK` policy the two buckets fill in a pinned order. `benefit_frame_cents` is the smaller of the policy's `frame_allowance_remaining_cents` **at the moment of the call** and the discounted frame amount. `benefit_lens_cents` is the discounted lens amount minus the policy's `lens_copay_cents`, floored at zero — a copay larger than the lens line does not create negative benefit. Under the `ESTIMATED` variant, `benefit_applied_cents` is simply `benefit_frame_cents` plus `benefit_lens_cents`.

**Step five: the customer's pre-FSA balance** is the net amount minus `benefit_applied_cents`.

**Step six: the FSA bucket.** `fsa_applied_cents` is the smallest of three numbers: the `fsa_amount_cents` the customer offered on the confirm request, the customer's `fsa_balance_cents`, and the pre-FSA balance. FSA dollars are applied only at confirmation; at order creation the offered amount is treated as zero, so a draft order always shows `fsa_applied_cents` of zero. `customer_due_cents` is the pre-FSA balance minus `fsa_applied_cents`.

**Confirmation.** The owning customer confirms a `DRAFT` order, optionally offering an `fsa_amount_cents` contribution. Confirmation advances the order's two parallel dimensions together on this one trigger: `fulfillment_status` moves `DRAFT → CONFIRMED` and `payment_status` moves `UNPAID → AUTHORIZED`. It is guarded by five preconditions. The order must be in `DRAFT`. The referenced prescription's `status` must be `VERIFIED`, or the confirm is refused with `ERR_PRESCRIPTION_NOT_VERIFIED`. That prescription's `expires_at` must be strictly after the logical clock, or the confirm is refused with `ERR_PRESCRIPTION_EXPIRED`. If the order's `delivery_method` is `BOPIS`, the destination store's `status` must be `OPEN`, or the confirm is refused with `ERR_STORE_CLOSED`. The order's `benefit_frame_cents` must not exceed the policy's `frame_allowance_remaining_cents` — the reservation may not over-draw the allowance — or the confirm is refused with `ERR_INSUFFICIENT_BENEFIT`. And the offered `fsa_amount_cents` must not exceed the customer's `fsa_balance_cents`, or the confirm is refused with `ERR_INSUFFICIENT_FSA`.

A successful confirmation runs a four-link cascade. The order is re-quoted under the `ESTIMATED` variant against the policy's current remaining allowance and the customer's current balance, `fsa_applied_cents` is set, the customer's `fsa_balance_cents` is debited by exactly that amount, and the order's `version` increments — **exactly once** for the whole confirmation, even though the cascade later also writes `active_claim_id` onto the same order. A `DRAFT` order created at `version` 1 is therefore at `version` 2 once confirmed, whatever else the cascade does. That produces a lab order for this order in `QUEUED`, with `remake_count` zero and `is_remake` false. The lab order's arrival in turn produces — but only when the customer has a non-null `insurance_policy_id` — an insurance claim in `SUBMITTED`, whose `policy_id` is copied from the customer, whose `service_lines` array is empty, and whose `reserved_frame_benefit_cents` equals the order's `benefit_frame_cents`; the order's `active_claim_id` is pointed at it. And that claim, finally, debits its policy: `frame_allowance_remaining_cents` decreases by exactly `reserved_frame_benefit_cents`. A self-pay customer stops at the lab order; no claim and no debit occur.

**Cancellation.** The owning customer or a `PlatformAdmin` may cancel an order whose `fulfillment_status` is `DRAFT`, `CONFIRMED`, or `IN_LAB`, optionally supplying a free-text `reason`. Any other fulfillment state — an order already `READY_FOR_PICKUP`, `SHIPPED`, `DELIVERED`, or `CANCELLED` — is refused with `ERR_INVALID_STATE`. Cancellation runs the mirror-image four-link cascade. The order's `fulfillment_status` becomes `CANCELLED`. Its payment dimension moves on its own axis: a `payment_status` of `AUTHORIZED` becomes `REFUNDED` and the customer's `fsa_balance_cents` is credited back by exactly the order's `fsa_applied_cents`, while a `payment_status` of `UNPAID` simply stays `UNPAID` and no FSA credit occurs. The cancellation then reaches the order's lab orders — every lab order ever minted against this order, remakes included: each one whose `status` is any of `QUEUED`, `IN_PRODUCTION`, `REMAKE_QUEUED`, or `QC_PASSED` transitions to `CANCELLED` and its `version` increments, while any lab order already `SHIPPED`, `DELIVERED` or `CANCELLED` is left where it stands. The lab order's cancellation reaches the claim: the order's `active_claim_id` claim, if its `status` is anything other than `VOID`, transitions to `VOID`. And the claim's voiding reaches the policy: `frame_allowance_remaining_cents` is credited back by exactly the claim's `reserved_frame_benefit_cents`, and the order's `active_claim_id` is cleared to null. The order's `version` increments **exactly once** across the whole cancel cascade, no matter how many of its links fire.

Orders may be read individually — the read returns the full money breakdown — and listed with filters on `customer_id`, `prescription_id`, `frame_id`, `store_id`, `exam_appointment_id`, `material_option_id`, `active_claim_id`, and `fulfillment_status`.

### 3.7. The Lab: Production, QC, the Remake Cycle, Shipment, and Handover

A lab order is created by an order confirmation (or, as §3.9 describes, by an approved warranty claim), always in `QUEUED`, always with `remake_count` at zero and `qc_failure_reason` and `delivered_at` null. It carries an `order_id` back to its parent, and its `shipped_to_store_id` and `active_warranty_claim_id` both start null.

A `LabTechnician` starts production, advancing the lab order to `IN_PRODUCTION`. That transition is legal from two distinct states, and the difference matters. Starting from `QUEUED` — a first run — also drives the parent order's fulfillment dimension `CONFIRMED → IN_LAB`, incrementing the parent order's `version` as well as the lab order's. Starting from `REMAKE_QUEUED` — a re-run after a failed inspection — closes the production cycle and touches only the lab order's own `version`; the parent order is already `IN_LAB` and does not move.

Quality control is recorded with a `result` of either `PASS` or `FAIL` on a lab order that is `IN_PRODUCTION`. A `PASS` advances the lab order `IN_PRODUCTION → QC_PASSED`, clears `qc_failure_reason` back to null, and increments `version`. A `FAIL` sends it back around the loop: it advances `IN_PRODUCTION → REMAKE_QUEUED`, increments `remake_count` by one, records the supplied `failure_reason` on `qc_failure_reason`, and increments `version`. A `FAIL` submitted without a `failure_reason` is refused with `ERR_INVALID_REQUEST`. And the loop is bounded: a failure is only accepted while `remake_count` is **strictly below two**, so the first and second failures are recorded and a third is refused with `ERR_REMAKE_LIMIT_EXCEEDED`.

Shipping a `QC_PASSED` lab order is the payment-capture event. The technician ships; if the parent order's `delivery_method` is `BOPIS`, the destination store must be `OPEN` or the ship is refused with `ERR_STORE_CLOSED`, and `shipped_to_store_id` is set to the parent order's `store_id`. For a `SHIP` order, `shipped_to_store_id` stays null. The lab order advances `QC_PASSED → SHIPPED`, and the parent order advances along **both** of its parallel dimensions: `fulfillment_status` moves `IN_LAB → READY_FOR_PICKUP` for a `BOPIS` order or `IN_LAB → SHIPPED` for a `SHIP` order, while `payment_status` moves `AUTHORIZED → CAPTURED`. The payment dimension advances on the fulfillment trigger but remains tracked independently. Both the lab order's and the parent order's `version` increment.

Handover is a `StoreAssociate`'s act — the BOPIS counter or the courier confirmation — and it advances a `SHIPPED` lab order to `DELIVERED`. It stamps `delivered_at` with the logical clock at that instant, formatted as an ISO 8601 UTC timestamp with three fractional digits, which is the anchor for the entire warranty window, and it advances the parent order's `fulfillment_status` from `READY_FOR_PICKUP` or from `SHIPPED` to `DELIVERED`. Both `version` counters increment. `DELIVERED` and `CANCELLED` are the lab order's terminal states.

Every one of those three bubble-ups is **guarded on the parent's current fulfillment state**, and a guard that does not match is silently skipped rather than raising: `start` moves the parent only if it is `CONFIRMED`, `ship` only if it is `IN_LAB`, `deliver` only if it is `READY_FOR_PICKUP` or `SHIPPED`, and the payment dimension moves to `CAPTURED` only from `AUTHORIZED`. A lab order whose parent has already moved past the guarded state therefore completes its own transition normally while leaving the parent — and the parent's `version` — untouched. The lab order's own transition is never refused on account of the parent. Lab orders may be read individually and listed with filters on `order_id`, `shipped_to_store_id`, `active_warranty_claim_id`, and `status`.

### 3.8. Insurance: Reserving Benefit, Adjudicating It, and Paying Out of Network

A claim is born in one of two ways. The first is automatic: an order confirmation mints a `SUBMITTED` claim with an empty `service_lines` array for any customer who has a policy, as §3.6 describes. The second is explicit — a `BenefitsAdmin` files a claim against an existing order, naming the `order_id`, an array of `service_lines`, and the `expected_order_version` that §2.7 requires. Each element of `service_lines` is an object carrying a `code` and a `billed_cents` amount, and the array is significant in **index-ascending order**.

An explicit filing **supersedes**. Any existing non-`VOID` claim on that order — the claim the order's `active_claim_id` currently points at — transitions to `VOID`, which credits its policy's `frame_allowance_remaining_cents` back by exactly its `reserved_frame_benefit_cents`. The new claim then reserves afresh: its `reserved_frame_benefit_cents` is set to the order's current `benefit_frame_cents`, and the policy's `frame_allowance_remaining_cents` is debited by that amount. The order's `active_claim_id` is repointed at the new claim and the order's `version` increments — exactly once for the whole filing, which is precisely why the next filing needs a fresh `expected_order_version`. The new claim's `policy_id` is the policy of the order's customer, its `status` is `SUBMITTED`, its `allowed_amount_cents` is null, its `approved_amount_cents` and `reimbursed_amount_cents` are zero, and its `denial_reason` is null. Nothing forbids filing against a self-pay order: the customer simply has no policy, so the new claim's `policy_id` is null, no policy is debited, and the reservation — the order's `benefit_frame_cents`, which is zero for an uninsured order — is recorded on the claim all the same. Such a claim can never be reimbursed, because reimbursement requires an `OUT_OF_NETWORK` policy.

**Adjudication.** A `BenefitsAdmin` records the insurer's ruling on a `SUBMITTED` claim by supplying a `decision`. A `decision` of `APPROVED` advances the claim `SUBMITTED → ADJUDICATED_APPROVED` and requires an `allowed_amount_cents` that is present and at least zero; a missing or negative value is refused with `ERR_INVALID_REQUEST`. The supplied figure is written to the claim's `allowed_amount_cents`, and what happens next turns on the policy's `network`:

- **`IN_NETWORK`.** The claim's `approved_amount_cents` becomes the smaller of the parent order's `benefit_applied_cents` as computed under the `ESTIMATED` variant and the insurer's `allowed_amount_cents`. The parent order is then re-quoted under the **`FINAL` variant**. Under `FINAL`, `benefit_applied_cents` is replaced by the smaller of the `ESTIMATED` `benefit_applied_cents` and the claim's `allowed_amount_cents`; `customer_due_cents` becomes the net amount (the subtotal less the discount) minus that new `benefit_applied_cents` minus the already-committed `fsa_applied_cents`; and the order's `quote_variant` becomes `FINAL`. Nothing else is recomputed — `subtotal_cents`, `discount_cents`, `benefit_frame_cents`, `benefit_lens_cents` and `fsa_applied_cents` all retain the values the `ESTIMATED` run gave them. The consequence is that identical order data yields a different `customer_due_cents` under `FINAL` than under `ESTIMATED` whenever the insurer's `allowed_amount_cents` comes in below the retailer's estimate — the shortfall lands on the customer.
- **`OUT_OF_NETWORK`.** The claim's `approved_amount_cents` is zero and the parent order is **not** re-quoted at all; its `quote_variant` stays `ESTIMATED`. Out-of-network money moves through reimbursement, not through the order. A claim carrying no policy at all — the self-pay filing above — takes this same branch: `approved_amount_cents` zero, no re-quote.

A `decision` of `DENIED` advances the claim `SUBMITTED → ADJUDICATED_DENIED` and requires a `denial_reason`; a denial without one is refused with `ERR_INVALID_REQUEST`. The supplied text is recorded on `denial_reason`, and the claim's `version` increments. Note what a denial does **not** do: the reserved frame benefit **stays reserved** on the policy. Only a void releases it.

**Reimbursement.** An `ADJUDICATED_APPROVED` claim on an `OUT_OF_NETWORK` policy is paid by a `BenefitsAdmin` with an empty request body, advancing it `ADJUDICATED_APPROVED → REIMBURSED`. The attempt is refused with `ERR_INVALID_STATE` when the policy's `network` is `IN_NETWORK` — in-network claims are never reimbursed to the member — and equally with `ERR_INVALID_STATE` when the claim carries no policy at all, and refused with `ERR_ANNUAL_MAX_EXCEEDED` when the policy has no headroom, meaning its `annual_max_cents` minus its `annual_reimbursed_cents` is zero or below.

The payout walks the claim's `service_lines` in index-ascending order and **rounds each line before summing**. For each line, the schedule cap is the value the policy's `oon_fee_schedule` maps the line's `code` to, or zero when the map has no entry for that code. The eligible amount for the line is the smaller of the line's `billed_cents` and that schedule cap. The line's reimbursement is the eligible amount multiplied by the policy's `oon_reimburse_pct` and rounded half up to whole cents. Those per-line reimbursements are then added together. **The rounding order is pinned and consequential**: rounding each line and then summing produces a different total than summing the raw products and rounding once, and only the first is correct.

The claim's `reimbursed_amount_cents` is the smaller of that total and the policy's remaining annual headroom — `annual_max_cents` minus `annual_reimbursed_cents` — so a claim may be paid out only partially when it exhausts the year. The policy's `annual_reimbursed_cents` is then increased by exactly the amount paid, and the claim's `version` increments.

**Voiding.** A claim whose `status` is `SUBMITTED`, `ADJUDICATED_APPROVED`, or `ADJUDICATED_DENIED` goes `VOID` in exactly two circumstances: its parent order is cancelled, or a superseding claim is filed against that order. In both, the compensating edge restores the exact benefit dollars the claim reserved — the policy's `frame_allowance_remaining_cents` is credited by the claim's `reserved_frame_benefit_cents` — and the order's `active_claim_id` is either cleared (on cancellation) or repointed at the superseding claim. The claim's `version` increments. `ADJUDICATED_DENIED`, `REIMBURSED` and `VOID` are the claim's terminal states. Claims may be read individually and listed with filters on `order_id`, `policy_id`, and `status`.

### 3.9. Warranty: Filing, Liability, and the Remake That Begets a Lab Order

A customer files a warranty claim against a delivered pair of glasses by naming the `lab_order_id`, their `customer_id`, a `reason`, and the `expected_lab_order_version` that §2.7 requires. The `reason` is one of `MANUFACTURER_DEFECT` (the lab got it wrong), `CUSTOMER_DAMAGE` (the customer got it wrong), or `RX_CHANGE` (nobody got it wrong; the eyes moved). The claim is created in `OPEN` with `remake_lab_order_id` and `denial_reason` null. The `customer_id` is subjected to the two checks §2.9 declares and no third one: it must name a customer that exists, and it must be the acting `Customer`'s own `X-User-ID`. The server does **not** additionally require that it match the customer on the lab order's parent order.

Two gates guard the filing. The target lab order's `status` must be `DELIVERED`, with a non-null `delivered_at` — glasses still in the lab cannot break — and any other status is refused with `ERR_LAB_ORDER_NOT_DELIVERED`. And the filing must fall inside the warranty window: the system counts the whole days elapsed from the lab order's `delivered_at` to the current logical clock by dividing the elapsed time by one day and rounding **down**, and refuses the filing with `ERR_WARRANTY_EXPIRED` when that count is **greater than** 365. A filing at exactly 365 days is inside the window and is accepted; a filing at 366 days is not.

Like an insurance claim, a warranty claim **supersedes**. Any existing `OPEN` claim on the same lab order transitions `OPEN → SUPERSEDED`, its `version` increments, and the lab order's `active_warranty_claim_id` is repointed at the new claim — which also increments the lab order's `version`, which is why a second filing needs a fresh `expected_lab_order_version`.

**The remake liability.** At filing, and once only, the system freezes what the customer will owe for the replacement pair on `customer_charge_cents`, keying the charge on the `reason` and on the days-since-delivery count above. A `MANUFACTURER_DEFECT` costs the customer nothing at all — the charge is zero. An `RX_CHANGE` is free during a thirty-day grace period: when the count of whole days since delivery is thirty or fewer the charge is zero, and beyond thirty days the customer pays half of the parent order's frozen `lens_upcharge_cents`, floored to whole cents. `CUSTOMER_DAMAGE` carries the same half-of-the-lens-upcharge share, floored to whole cents, **plus** a flat fifteen-dollar — 1,500-cent — reshipping fee, with no grace period of any kind; a pair damaged the day after handover is charged exactly as much as one damaged eleven months later.

**The decision.** A `StoreAssociate` rules on an `OPEN` warranty claim by supplying a `decision`. `APPROVED` advances it `OPEN → APPROVED` and mints a brand-new lab order against the same `order_id`: that replacement enters `QUEUED` with `remake_count` back at zero, `is_remake` set to true, `shipped_to_store_id`, `active_warranty_claim_id`, `qc_failure_reason` and `delivered_at` all null, and its `id` is written to the warranty claim's `remake_lab_order_id`. Only the warranty claim's `version` increments; neither the original lab order nor the parent order is written. The remake lab order then walks the full production path of §3.7 from the beginning — start, QC, ship, deliver — and its own delivery stamps a fresh `delivered_at`, opening a fresh warranty window against which yet another claim may one day be filed. Because the parent order is by then `DELIVERED`, every one of those transitions fails the bubble-up guards of §3.7 and leaves the parent order — its `fulfillment_status`, its `payment_status` and its `version` — exactly where the original run left it. `DENIED` advances the claim `OPEN → DENIED` and requires a `denial_reason`; a denial without one is refused with `ERR_INVALID_REQUEST`, and the text is recorded on `denial_reason`. Either way the claim's `version` increments, and `APPROVED`, `DENIED` and `SUPERSEDED` are all terminal. Warranty claims may be read individually and listed with filters on `lab_order_id`, `customer_id`, `remake_lab_order_id`, and `status`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/optical` prefix. Operations that bring a new resource into existence return **201 Created**; operations that read, modify, or transition an existing resource return **200 OK**. Every response — success or failure — is wrapped in the envelope of §2.2. The table below is a routing summary only: the request payloads, the response side effects, and the trigger conditions for every error live in §2 and §3 and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/optical/insurance-policies` | Register a vision plan. | `PlatformAdmin` |
| GET | `/optical/insurance-policies/{id}` | Read a policy, including its live frame-allowance and annual-reimbursement ledgers. | `PlatformAdmin`, `BenefitsAdmin`, `Customer` |
| POST | `/optical/stores` | Register a retail store with exam-chair capacity and turnover buffer. | `PlatformAdmin` |
| POST | `/optical/frames` | Add a frame to the catalog. | `PlatformAdmin` |
| GET | `/optical/frames/{id}` | Read a frame, including its live try-on availability. | `PlatformAdmin`, `StoreAssociate`, `Customer`, `OpticianVerifier`, `LabTechnician`, `BenefitsAdmin` |
| GET | `/optical/frames/{id}/try-on-kit-items` | List every try-on kit item that holds (or held) this frame. | `PlatformAdmin`, `StoreAssociate` |
| POST | `/optical/lens-options` | Add a lens material or coating to the catalog. | `PlatformAdmin` |
| POST | `/optical/customers` | Register a customer, optionally attaching a vision policy and an FSA balance. | `PlatformAdmin` |
| GET | `/optical/customers/{id}` | Read a customer, including their FSA balance, lifetime kit count and return-risk score. | `PlatformAdmin`, `StoreAssociate`, `Customer` |
| GET | `/optical/customers` | List customers, optionally filtered by the policy they are enrolled in. | `PlatformAdmin`, `StoreAssociate` |
| POST | `/optical/_clock/set_current_utc` | Test-driving capability: set the server's logical UTC clock, expiring prescriptions and flipping overdue kits. | `PlatformAdmin` |
| POST | `/optical/prescriptions` | Capture a prescription and pupillary distance; enters verification awaiting an optician. | `Customer`, `StoreAssociate` |
| GET | `/optical/prescriptions/{id}` | Read a prescription. | `Customer`, `OpticianVerifier`, `StoreAssociate`, `PlatformAdmin` |
| GET | `/optical/customers/{id}/prescriptions` | List a customer's prescriptions. | `Customer`, `OpticianVerifier`, `StoreAssociate`, `PlatformAdmin` |
| POST | `/optical/prescriptions/{id}/verify` | Optician verifies or rejects a submitted prescription. | `OpticianVerifier` |
| POST | `/optical/prescriptions/{id}/resubmit` | Customer corrects and resubmits a rejected prescription. | `Customer` |
| POST | `/optical/home-try-on-kits` | Request a home try-on kit holding one to five frames over a closed window. | `Customer` |
| GET | `/optical/home-try-on-kits/{id}` | Read a kit. | `Customer`, `StoreAssociate`, `PlatformAdmin` |
| GET | `/optical/customers/{id}/home-try-on-kits` | List a customer's try-on kits. | `Customer`, `StoreAssociate`, `PlatformAdmin` |
| GET | `/optical/home-try-on-kits/{id}/items` | List the items in a kit with their outcomes. | `Customer`, `StoreAssociate`, `PlatformAdmin` |
| POST | `/optical/home-try-on-kits/{id}/ship` | Store associate ships the kit. | `StoreAssociate` |
| POST | `/optical/home-try-on-kits/{id}/return` | Customer returns the kit, naming the frames they intend to buy. | `Customer` |
| POST | `/optical/orders` | Build an order; freezes the lens upcharge and produces an estimated quote. | `Customer` |
| GET | `/optical/orders/{id}` | Read an order and its full money breakdown. | `Customer`, `StoreAssociate`, `BenefitsAdmin`, `PlatformAdmin` |
| GET | `/optical/orders` | List orders with foreign-key filters. | `StoreAssociate`, `BenefitsAdmin`, `PlatformAdmin` |
| POST | `/optical/orders/{id}/confirm` | Confirm and authorize the order; mints the lab order and, for insured customers, the reserving insurance claim. | `Customer` |
| POST | `/optical/orders/{id}/cancel` | Cancel the order; runs the four-link cancel cascade. | `Customer`, `PlatformAdmin` |
| GET | `/optical/lab-orders/{id}` | Read a lab order. | `LabTechnician`, `StoreAssociate`, `Customer`, `PlatformAdmin` |
| GET | `/optical/lab-orders` | List lab orders with foreign-key filters. | `LabTechnician`, `StoreAssociate`, `PlatformAdmin` |
| POST | `/optical/lab-orders/{id}/start` | Move a queued or remake-queued lab order into production. | `LabTechnician` |
| POST | `/optical/lab-orders/{id}/qc` | Record a QC result; a failure sends the lab order back around the remake cycle. | `LabTechnician` |
| POST | `/optical/lab-orders/{id}/ship` | Ship the finished glasses to the pickup store or to the customer, and capture payment. | `LabTechnician` |
| POST | `/optical/lab-orders/{id}/deliver` | Hand the glasses over; starts the warranty window. | `StoreAssociate` |
| POST | `/optical/insurance-claims` | File (or re-file) an insurance claim against an order; guarded by the order's version. | `BenefitsAdmin` |
| GET | `/optical/insurance-claims/{id}` | Read a claim. | `BenefitsAdmin`, `PlatformAdmin`, `Customer` |
| GET | `/optical/insurance-claims` | List claims with foreign-key filters. | `BenefitsAdmin`, `PlatformAdmin` |
| POST | `/optical/insurance-claims/{id}/adjudicate` | Record the insurer's decision; an in-network approval re-quotes the parent order. | `BenefitsAdmin` |
| POST | `/optical/insurance-claims/{id}/reimburse` | Pay an approved out-of-network claim. | `BenefitsAdmin` |
| POST | `/optical/warranty-claims` | File a warranty claim against a delivered lab order; guarded by the lab order's version. | `Customer` |
| GET | `/optical/warranty-claims/{id}` | Read a warranty claim. | `Customer`, `StoreAssociate`, `PlatformAdmin` |
| GET | `/optical/warranty-claims` | List warranty claims with foreign-key filters. | `StoreAssociate`, `PlatformAdmin` |
| POST | `/optical/warranty-claims/{id}/decide` | Approve (minting a remake lab order) or deny an open warranty claim. | `StoreAssociate` |
| POST | `/optical/exam-appointments` | Book an eye exam against the store's chair capacity. | `Customer` |
| GET | `/optical/exam-appointments/{id}` | Read an appointment. | `Customer`, `StoreAssociate`, `PlatformAdmin` |
| GET | `/optical/exam-appointments` | List appointments with foreign-key filters. | `StoreAssociate`, `PlatformAdmin` |
| POST | `/optical/exam-appointments/{id}/complete` | Close the exam and link the prescription it produced. | `StoreAssociate` |

## 5. Error Code Catalogue

The trigger condition for every code below is specified in §2 and §3, next to the rule it enforces. When more than one condition holds, §2.9 decides which code is returned.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_FRAME_NOT_FOUND` | 404 |
| `ERR_LENS_OPTION_NOT_FOUND` | 404 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_KIT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_LAB_ORDER_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_LAB_ORDER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRESCRIPTION_NOT_VERIFIED` | 409 |
| `ERR_LAB_ORDER_NOT_DELIVERED` | 409 |
| `ERR_STORE_CLOSED` | 409 |
| `ERR_PD_OUT_OF_RANGE` | 422 |
| `ERR_LENS_INCOMPATIBLE_WITH_RX` | 422 |
| `ERR_COATING_INCOMPATIBLE` | 422 |
| `ERR_FRAME_DISCONTINUED` | 422 |
| `ERR_PRESCRIPTION_OWNER_MISMATCH` | 422 |
| `ERR_PRESCRIPTION_EXPIRED` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_KIT_EMPTY` | 422 |
| `ERR_KIT_SIZE_EXCEEDED` | 422 |
| `ERR_CUSTOMER_TRYON_BLOCKED` | 403 |
| `ERR_TRYON_WINDOW_CONFLICT` | 409 |
| `ERR_TRYON_STOCK_UNAVAILABLE` | 409 |
| `ERR_EXAM_SLOT_CONFLICT` | 409 |
| `ERR_BOPIS_STORE_REQUIRED` | 422 |
| `ERR_REMAKE_LIMIT_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_BENEFIT` | 422 |
| `ERR_INSUFFICIENT_FSA` | 422 |
| `ERR_ANNUAL_MAX_EXCEEDED` | 422 |
</content>
</invoke>
