# Mail-Order Contact Lens API — Product Requirements Document

## 1. Introduction

Selling contact lenses by mail is a regulated act of dispensing, not a retail transaction. Every box that leaves the warehouse must be traceable to a prescription that a licensed eye-care provider actually wrote, that has not lapsed, and that authorises the quantity being shipped. The operational difficulty is that the prescriber is a third party who owes the retailer nothing: they may confirm a prescription, correct its powers, deny it outright, or simply never answer. This API exists to make that silence legally and computationally tractable, by running a passive verification clock against the prescriber and treating expiry of that clock as agreement.

Around that verification spine sit the commercial mechanics that patients actually experience. Warehouses substitute lens SKUs when a parameter is not stocked, and each substitution must be scored against the prescription before it is allowed to ship. Patients on out-of-network vision plans need reimbursement paperwork priced against an annual allowance that several claims compete for. Torn lenses and mid-cycle prescription changes come back as returns whose value has to be prorated across partially used boxes. Auto-reorder subscriptions must keep shipping on a cadence derived from the wear schedule — and must stop shipping the moment a compliance hold opens.

The requirements below describe a single service that holds all of these concerns in one consistent state. Two themes run through the whole specification and should be read as constraints on every endpoint: money and allowance are tracked as **derived ledgers** that are recomputed from live rows rather than incremented in place, so that a cancellation or a void releases exactly what the forward operation consumed; and compliance-relevant decisions are **segregated**, so the officer who opens a hold cannot release it and the officer who approves a refund cannot pay it.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply across the entire API. Everything here holds unless a specific workflow in §3 narrows it.

### 2.1. Caller Identity and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined. If the header pair is present but the declared role is not one of the roles authorised for the addressed endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, spelled exactly as follows: `Customer`, `Prescriber`, `ComplianceOfficer`, `FulfillmentOperator`, and `PlatformAdmin`.

Two of these roles are **entity-backed**, meaning the identifier in `X-User-ID` names a persisted row:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer. Ownership checks on any resource that references a Customer compare that resource's customer foreign key to `X-User-ID`: a patient may address only their own prescriptions, orders, auto-reorder schedules, return requests, reimbursement claims, reorder holds and ledger.
- When `X-User-Role` is `Prescriber`, `X-User-ID` is the `id` of the acting Prescriber. Ownership checks compare the addressed resource's prescriber foreign key to `X-User-ID`: a provider may respond only to verification requests addressed to them, and may file disputes only against prescriptions that name them.

A failed ownership check yields `ERR_IDENTITY_MISMATCH` (HTTP 403). Resources that reference neither a Customer nor a Prescriber — vision plans, lens SKUs, equivalence mappings — carry no ownership dimension, so no ownership comparison is performed when they are read.

The remaining three roles are **opaque**: when `X-User-Role` is `ComplianceOfficer`, `FulfillmentOperator`, or `PlatformAdmin`, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server records it where a workflow demands an actor — as `opened_by_user_id` and `released_by_user_id` on a reorder hold, as `approved_by_user_id` and `settled_by_user_id` on a return request, as `resolved_by_user_id` on a prescriber dispute, and as `actor_user_id` on every compliance event — but it never compares it to any row's `id`. `ComplianceOfficer` is the compliance desk: it opens verification rounds, runs sweeps, manages holds, and performs both halves of the return workflow (with the halves necessarily performed by two different `X-User-ID` values). `FulfillmentOperator` is warehouse staff: it substitutes, ships, delivers and drives the auto-reorder run, and never touches holds, claims or disputes. `PlatformAdmin` owns reference-data setup and the logical clock and may additionally perform any other operation in this specification, but is still bound by the segregation-of-duties rules in §2.8.

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

### 2.3. Pagination and List Ordering

List endpoints accept two query parameters. `limit` caps the number of rows returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` is the number of rows to skip and defaults to 0. A value outside those bounds is a range violation and is rejected as a malformed request.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending. The one exception is the compliance-event trail for a prescription, which is ordered by `occurred_at` ascending and, where two events share an instant, by insertion order.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object, where `total_count` counts every row matching the filters before pagination is applied and `has_more` is true when rows remain beyond the returned page.

### 2.4. Common Resource Properties and Snapshot Discipline

Insurance plans, products, lens equivalences, prescribers, customers, prescriptions, verification requests, orders, reorder holds, auto-reorder schedules, return requests, reimbursement claims and prescriber disputes all carry the same four system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations caused by a cascade rather than by a direct request against that row.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation of the row. Recomputation of a derived field counts as a mutation: when a customer's ledgers are reconciled, that customer's `updated_at` and `version` both move.

Compliance events are the single exception. A compliance event is an append-only audit record and carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never modified after it is written.

Several fields are deliberate **snapshots**, captured once and then immune to later edits of their source. An order's `unit_price_cents` and `lenses_per_box_at_capture` are copied from the ordered product at creation, so repricing or repackaging that product afterwards never changes an existing order or the value of a return prorated from it. A verification request's `channel` is a snapshot of the prescriber's `contact_channel` at send time. A reimbursement claim prices itself against the plan named by its `insurance_plan_id` at generation time.

Every entity that carries a lifecycle exposes it in a `status` field, except the Order, which carries two independent lifecycle fields, `verification_state` and `fulfillment_state`. Enumerated values are exact, case-sensitive strings and are listed with the workflow that owns them in §3.

### 2.5. The Logical Clock and Business-Hour Arithmetic

All temporal comparisons in this system — passive verification deadlines, contact cooldowns, prescription expiry, claim windows, auto-reorder due dates — read a single server-held **logical clock** rather than wall-clock time. An administrator sets it by supplying `current_utc`, and any operator may read `current_utc` back. Until it has been set for the first time, the logical clock reads `2026-08-01T00:00:00Z`. Setting the clock has no side effect other than moving the instant that every subsequent deadline, sweep and window comparison reads.

Verification deadlines and contact cooldowns are not measured in elapsed hours but in **business hours**. A business day runs from 08:00 UTC to 17:00 UTC, which is nine business hours per day, and business days are Monday, Tuesday, Wednesday, Thursday and Friday. Saturday and Sunday contribute nothing.

Walking a business-hour budget forward from a starting instant proceeds as follows, and the same walk is reused wherever this document refers to "advancing *n* business hours":

1. Place a cursor on the starting instant.
2. Normalise the cursor. If it falls on a business day but earlier than 08:00 UTC, move it to 08:00 UTC on that same day. If it falls at or after 17:00 UTC, or falls on a Saturday or Sunday, move it to 08:00 UTC on the next business day.
3. While budget remains, consume from the cursor whichever is smaller: the whole remaining budget, or the number of hours between the cursor and 17:00 UTC on the cursor's day. If budget still remains after reaching 17:00 UTC, move the cursor to 08:00 UTC on the next business day and continue.
4. The resulting cursor is the answer, expressed as a millisecond-resolution ISO 8601 UTC timestamp.

Note that the normalisation step is applied before any budget is consumed, so a request logged at a weekend instant begins its budget at the following Monday morning.

### 2.6. Money in Whole Cents and Rounding Discipline

Every monetary quantity in this system is an integer number of cents. There are no fractional-cent fields and no decimal money fields. Order pricing, return settlement, and claim reimbursement all produce integers, and the API returns them as integers.

Wherever a division or a percentage multiplication is performed on money, the result is rounded to a whole cent using **round half up** — that is, a residue of exactly one half cent rounds upward in magnitude. Two computations deliberately depart from that default and say so at the point of use: the torn-lens cap is taken with a **floor** rather than a round, and the parameter deviation index is computed entirely in integer hundredths so that no binary floating-point residue can shift a boundary comparison.

Non-monetary decimals — `coinsurance_rate`, `base_curve`, `diameter`, `sphere_min`, `sphere_max`, `sphere_step`, `od_sphere`, `os_sphere`, `fulfilled_od_sphere`, `fulfilled_os_sphere` and `parameter_deviation_index` — preserve their declared scale. `coinsurance_rate` carries two decimal places and must be at least 0.00 and at most 1.00. `base_curve` and `diameter` carry two decimal places and are expressed in millimetres. Sphere powers carry two decimal places and may be negative. `parameter_deviation_index` is presented with exactly two decimal places.

### 2.7. Derived Ledgers and Reconciliation Invariants

A Customer row is more than a name and an email: it carries eight derived counters that the rest of the system reconciles against. None of them is ever incremented blindly. Each is recomputed from live rows whenever an event could have changed it, so that a compensating operation releases exactly what the forward operation consumed. A newly registered patient has every counter at zero and `auto_reorder_enabled` false.

- `lifetime_charged_cents` is the sum of `total_cents` over every order of that customer whose `fulfillment_state` is anything other than `CANCELLED`.
- `lifetime_refunded_cents` is the sum of `settlement_cents` over that customer's return requests whose `status` is `SETTLED` and whose `settlement_channel` is `CASH_REFUND`.
- `net_cash_position_cents` is `lifetime_charged_cents` less `lifetime_refunded_cents`. This equality is the money invariant, **INV_MONEY**, and it must hold after every cancellation, settlement and cascade.
- `store_credit_cents` is the running store-credit balance, credited whenever a return settles through the `STORE_CREDIT` channel.
- `allowance_used_cents` is the plan-year allowance the customer has consumed, computed as described below. This is the allowance invariant, **INV_ALLOWANCE**.
- `open_hold_count` is the number of that customer's reorder holds whose `status` is `OPEN`.
- `active_schedule_count` is the number of that customer's auto-reorder schedules whose `status` is `ACTIVE`.
- `auto_reorder_enabled` is true exactly when `active_schedule_count` is greater than zero and `open_hold_count` is zero, and false in every other case.

The allowance ledger is reconciled over a half-open plan-year window. First locate the plan year: take the month-and-day anchor `plan_year_start_month_day` from the customer's plan and find its most recent occurrence at or before the current logical date; that is the plan-year start. The window runs from the plan-year start inclusive to the same anchor one year later exclusive, so a claim created exactly on the next plan-year anchor belongs to the next plan year and not to the current one. `allowance_used_cents` is then the sum of `applied_allowance_cents` over that customer's reimbursement claims whose `created_at` falls inside the window and whose `status` is `GENERATED` or `SUBMITTED`. Claims in `DRAFT` and claims in `VOIDED` contribute nothing. The value is recomputed after every claim generation and every claim void.

A prescription carries the parallel box ledger. `boxes_consumed` is the sum of `boxes_od` plus `boxes_os` over every order against that prescription whose `fulfillment_state` is not `CANCELLED`; this is the box invariant, **INV_BOXES**.

A dedicated reconciled read exposes the whole picture for one patient. It returns `customer_id`, `lifetime_charged_cents`, `lifetime_refunded_cents`, `net_cash_position_cents`, `store_credit_cents`, `allowance_used_cents`, `allowance_remaining_cents`, `open_hold_count`, `active_schedule_count` and `auto_reorder_enabled`, each recomputed from live rows at read time so that any drift between the stored counters and reality is directly observable. `allowance_remaining_cents` is the plan's `annual_allowance_cents` less `allowance_used_cents`, floored at zero; for a self-pay customer who carries no `insurance_plan_id` it is zero.

### 2.8. Segregation of Duties on Two-Person Workflows

Two workflows in this system are deliberately split across two people, and in both cases the second step is refused when it is attempted by the same operator who performed the first. Releasing a reorder hold requires an `X-User-ID` different from the hold's `opened_by_user_id`. Settling a return request requires an `X-User-ID` different from the request's `approved_by_user_id`. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). `PlatformAdmin` enjoys no exemption here.

Holds opened by a cascade rather than by a human record the literal string `"system"` in `opened_by_user_id`, which means any human operator may release them.

### 2.9. Optimistic Concurrency on Substitution and Dispute Filing

Exactly two write operations in this API participate in optimistic concurrency control, and both take a mandatory version field.

Applying a substitution to an order requires `expected_order_version` in the request body. The field is not optional. Its value must equal the order's current `version` — the value the caller last read back from that order. If the stored `version` differs, the substitution is refused with `ERR_STALE_ORDER_VERSION` (HTTP 412) and no field on the order changes, which prevents a warehouse operator from overwriting a substitution decision they never saw. A successful substitution increments the order's `version`, so the next substitution attempt must present the new value.

Filing a prescriber dispute requires `expected_prescription_version` in the request body, again non-optional, carrying the prescription `version` the prescriber last read. If the stored `version` differs, no dispute row is created and the request is refused with `ERR_STALE_PRESCRIPTION_VERSION` (HTTP 412) — a prescriber must not be able to dispute a version of a prescription that has already been corrected or superseded out from under them.

No other endpoint in this specification accepts a version field, and no other endpoint performs a version comparison.

### 2.10. Request Evaluation Order and Referential Resolution

When several checks could reject the same request, the outcome is determined by a fixed, total ordering. The first check that fails determines the response, and no later check is evaluated. This matters because a single call can violate three rules at once and the benchmark asserts a specific error identifier.

The ordering, from highest precedence downward:

1. **Caller identity present.** `X-User-ID` or `X-User-Role` missing or empty on any endpoint → `ERR_UNAUTHENTICATED` (401).
2. **Request well-formed.** On any endpoint with a request body or query parameters: a required field absent, a field of the wrong type, an enum value outside its declared domain, a numeric field outside its declared range, or an `expiry_date` that is not a valid calendar date → `ERR_INVALID_REQUEST` (400).
3. **Role permitted.** The value of `X-User-Role` is not among the roles listed for the endpoint in §4 → `ERR_UNAUTHORIZED` (403).
4. **Path row exists.** On any endpoint whose path contains an identifier, the `id` in the path does not name a stored row → the not-found code of the addressed entity, at HTTP 404: `ERR_INSURANCE_PLAN_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRESCRIBER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_VERIFICATION_REQUEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_REORDER_HOLD_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_RETURN_REQUEST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or `ERR_DISPUTE_NOT_FOUND` as appropriate. Where a path contains more than one identifier, they are resolved strictly left to right and the leftmost failure determines the response: a request for a lens equivalence under a product that does not exist reports `ERR_PRODUCT_NOT_FOUND` and never looks further right.
5. **Body references exist.** A foreign key in the request body that does not name a stored row → the not-found code of the *referenced* entity, at HTTP 404, drawn from the same list.
6. **Entity-backed ownership.** The caller's role is entity-backed and `X-User-ID` does not equal the `id` of the Customer or Prescriber that owns the addressed row → `ERR_IDENTITY_MISMATCH` (403).
7. **Segregation of duties.** On hold release and on return settlement, the acting `X-User-ID` equals the operator who performed the paired earlier step → `ERR_SEGREGATION_OF_DUTIES` (409).
8. **Order version current.** On substitution, `expected_order_version` does not equal the stored order `version` → `ERR_STALE_ORDER_VERSION` (412).
9. **Prescription version current.** On dispute filing, `expected_prescription_version` does not equal the stored prescription `version` → `ERR_STALE_PRESCRIPTION_VERSION` (412).
10. **Transition declared for the current state.** On any action endpoint, the requested trigger is not declared for the target row's current state — including any attempt from a terminal state and any repeat of an already-applied trigger → `ERR_INVALID_STATE_TRANSITION` (409). This code also covers a declared transition whose own state precondition fails and for which no more specific code exists: shipping an order whose `verification_state` is not `RX_CLEARED`, approving a return whose order is still `PENDING`, generating a claim whose order is not `DELIVERED`, or responding to a verification request that is no longer `SENT`. Where a specific code is declared for the failing precondition — `ERR_HOLD_OPEN_BLOCKS_ACTION`, `ERR_PRESCRIPTION_NOT_VERIFIED`, `ERR_SEGREGATION_OF_DUTIES` or `ERR_REFUND_EXCEEDS_CAPTURE` — that specific code is returned instead of this one.
11. Customer email uniqueness on patient registration → `ERR_DUPLICATE_EMAIL` (409).
12. Prescription not expired, on order placement, on the auto-reorder run and on prescription submit → `ERR_PRESCRIPTION_EXPIRED` (409).
13. Prescriber licence uniqueness within a state, on prescriber registration → `ERR_DUPLICATE_LICENSE` (409).
14. Expiry after issue, on prescription capture → `ERR_EXPIRY_BEFORE_ISSUE` (400).
15. Upload capture carries a document, on prescription capture and on submit → `ERR_CAPTURE_MODE_REQUIRES_DOCUMENT` (400).
16. Doctor-lookup capture names a prescriber, on prescription capture and on submit → `ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER` (400).
17. Self-report capture names a prescriber in free text, on prescription capture and on submit → `ERR_SELF_REPORT_REQUIRES_NAME` (400).
18. Validity intervals do not overlap, on prescription submit → `ERR_PRESCRIPTION_INTERVAL_OVERLAP` (409).
19. Prescription is verified, on schedule creation, schedule resume and hold release → `ERR_PRESCRIPTION_NOT_VERIFIED` (409).
20. Prescription is not invalidated, on order placement, order ship and substitution → `ERR_PRESCRIPTION_INVALIDATED` (409).
21. Prescriber is contactable, on opening a verification round → `ERR_PRESCRIBER_SUSPENDED` (409).
22. Response arrives inside the passive window, on a prescriber response → `ERR_VERIFICATION_WINDOW_CLOSED` (409).
23. Substitution deviation within the absolute limit → `ERR_PARAMETER_DEVIATION_EXCEEDED` (422).
24. Consent present where consent is required, on substitution → `ERR_CONSENT_REQUIRED` (422).
25. An active equivalence mapping exists, on substitution → `ERR_NO_EQUIVALENCE_MAPPING` (422).
26. Referenced product is active, on order placement, substitution and schedule creation → `ERR_PRODUCT_INACTIVE` (409).
27. No open dispute, on hold release → `ERR_OPEN_DISPUTE_BLOCKS_RELEASE` (409).
28. Prescriber contact cooldown respected, on opening a verification round → `ERR_PRESCRIBER_CONTACT_COOLDOWN` (429).
29. Prescriber pending-request capacity, on opening a verification round → `ERR_PRESCRIBER_REQUEST_CAPACITY` (409).
30. Verification round cap, on opening a verification round → `ERR_MAX_VERIFICATION_ROUNDS` (409).
31. No open hold, on order ship, schedule resume and the auto-reorder run → `ERR_HOLD_OPEN_BLOCKS_ACTION` (409).
32. Plan is not retired, on claim creation and claim generation → `ERR_PLAN_RETIRED` (409).
33. Plan is out of network, on claim creation and claim generation → `ERR_PLAN_NOT_OUT_OF_NETWORK` (422).
34. Itemised receipt present where the plan demands one, on claim generation → `ERR_ITEMIZED_RECEIPT_REQUIRED` (422).
35. Claim window open, on claim generation and claim submission → `ERR_CLAIM_WINDOW_CLOSED` (409).
36. Plan-year allowance remains, on claim generation → `ERR_ALLOWANCE_EXHAUSTED` (409).
37. Box authorisation not exceeded, on order placement and on the auto-reorder run → `ERR_BOX_AUTHORIZATION_EXCEEDED` (409).
38. Returned quantities within what the order shipped, on return creation → `ERR_RETURN_QUANTITY_EXCEEDS_ORDER` (422).
39. Refund within the captured amount, on return settlement → `ERR_REFUND_EXCEEDS_CAPTURE` (409).

Three of these checks behave differently on the auto-reorder run, because that endpoint is a batch sweep rather than a single-row action. Prescription expiry, open holds, and box authorisation are all evaluated per due schedule against that schedule's own prescription and customer, and a failure causes **that schedule to be skipped** rather than producing an error response; the run itself still returns HTTP 200. Negative quantities never reach the return-quantity check, because an out-of-range numeric value is already caught as a malformed request at step 2.

### 2.11. Cascade Discipline, Deferred Actions and the Compliance Trail

Several operations in this system mutate rows the caller never named. When they do, three rules hold. First, every cascade is applied in full — a cascade that touches four entity types touches all four before the response is returned, and each touched row has its `updated_at` refreshed and its `version` incremented. Second, wherever a cascade fans out over a set of sibling rows, those rows are processed in `created_at` ascending order, so that the resulting audit trail is deterministic. Third, every compliance-relevant transition against a prescription appends an append-only **compliance event**.

A compliance event names the `prescription_id` it belongs to, an `event_type`, the `subject_type` (the entity name the event concerns, such as `Order`) and the `subject_id` of the subject row, together with the `actor_role` and `actor_user_id` responsible and an optional human-readable `detail`. Cascades and sweeps that no human triggered record the literal string `System` as `actor_role` and `system` as `actor_user_id`. `occurred_at` is the logical clock value at the moment the event was recorded. The `event_type` values are exactly `RX_SUBMITTED`, `REQUEST_SENT`, `RESPONSE_RECEIVED`, `PASSIVE_PROMOTED`, `RX_EXPIRED`, `RX_INVALIDATED`, `HOLD_OPENED`, `HOLD_RELEASED`, `HOLD_ESCALATED`, `ORDER_BLOCKED`, `ORDER_CANCELLED`, `SUBSTITUTION_APPLIED`, `DISPUTE_FILED`, `DISPUTE_RESOLVED`, `CLAIM_VOIDED` and `SCHEDULE_PAUSED`.

Two endpoints are **deferred-action sweeps** rather than requests against a single row: the verification sweep and the auto-reorder run. Both examine every row that has become due against the logical clock and act on all of them within a single call, and both return a summary of what they did rather than a resource. Their internal ordering is specified with their workflows in §3 and is part of the contract.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Vision Plans, Lens SKUs and Equivalence Mappings

Before any patient can be served, an administrator loads three kinds of reference data. Each is administrator-owned; none of them may be authored by compliance, warehouse or patient roles.

A **vision plan** is registered with a `name` for display and a `network_status` of either `IN_NETWORK` or `OUT_OF_NETWORK`. Only out-of-network plans can ever have reimbursement paperwork generated against them. The plan's money rules are `annual_allowance_cents`, the maximum eligible spend reimbursed per plan year, which must be zero or greater, and `coinsurance_rate`, the member's share applied to whatever eligible spend sits above the allowance. Four optional fields shape the paperwork: `requires_itemized_receipt`, which defaults to true and, when true, forces claim generation to find a receipt identifier on the order; `covers_shipping`, which defaults to false and, when false, excludes the order's shipping charge from the base eligible spend; `claim_window_days`, the number of days after delivery within which a claim may be generated, defaulting to 90; and `plan_year_start_month_day`, the `MM-DD` anchor of the plan year, defaulting to `01-01`. A plan's `status` is `ACTIVE` or `RETIRED` and defaults to `ACTIVE`; retiring a plan flips it to `RETIRED`, after which claim creation and claim generation against it are both refused with `ERR_PLAN_RETIRED`.

A **product** is a sellable lens SKU. It is registered with a `brand`, a `name`, a `wear_schedule` of `DAILY_DISPOSABLE`, `BIWEEKLY` or `MONTHLY`, a `lenses_per_box` count of at least 1, and a `unit_price_cents` price per box of at least 1. Its fitting envelope is described by `base_curve` and `diameter` in millimetres, by `sphere_min` and `sphere_max` bounding the stocked powers (where `sphere_max` must be at least `sphere_min`), and by `sphere_step`, the granularity of stocked powers, which defaults to 0.25. A `material_family` string groups SKUs that share a lens material. A product's `status` is `ACTIVE` or `INACTIVE` and defaults to `ACTIVE`; deactivating a product sets `INACTIVE`, and thereafter it may be neither ordered, nor scheduled, nor substituted into — such attempts are rejected with `ERR_PRODUCT_INACTIVE`. Products may be browsed with filters on `wear_schedule`, `status` and `material_family`.

A **lens equivalence** is a directed edge between two products declaring how far a substitution may travel. It is authored against a path product, which becomes the mapping's `from_product_id`, and names a `to_product_id` as the SKU that may be fulfilled instead. Its `equivalence_class` is one of three values with distinct clinical meaning: `EXACT` mappings auto-approve, `CLINICAL` mappings are gated on the computed fitting deviation described in §3.6, and `MATERIAL_ONLY` mappings — SKUs related only by sharing a `material_family` — always require the patient to consent. Independently of the class, the flag `requires_patient_consent`, defaulting to false, forces consent when set. A mapping's `status` is `ACTIVE` or `RETIRED`, defaulting to `ACTIVE`; a `RETIRED` mapping cannot be used for substitution. Mappings touching a product can be listed with an optional `direction` filter, where `FROM` returns the rows whose `from_product_id` is the path product, `TO` returns the rows whose `to_product_id` is the path product, and omitting the filter returns both, alongside the usual `status` filter.

**Prescribers** complete the reference set. A provider is registered with a `full_name`, a `license_number`, a two-letter `license_state`, and a `contact_channel` of `FAX`, `PORTAL` or `EMAIL` that determines how verification reaches them. A licence number must be unique within a state; a collision is rejected with `ERR_DUPLICATE_LICENSE`. The boolean `directory_verified` defaults to false and is set true when the provider was matched from the authoritative provider directory — a distinction that shortens the passive verification clock, as §3.3 explains. A prescriber's `status` is `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`; suspension blocks any new verification contact and yields `ERR_PRESCRIBER_SUSPENDED`. Prescribers can be listed filtered by `license_state`, by `directory_verified` and by `status`.

### 3.2. Patient Records and Prescription Capture

A patient is registered by an administrator with a `full_name`, a contact `email` that must be unique across all patients, and a two-letter `state_code` of residence. An optional `insurance_plan_id` links the patient to a vision plan; when it is absent the patient is self-pay and no reimbursement paperwork is possible for them. A duplicate email is rejected with `ERR_DUPLICATE_EMAIL`, and a plan identifier that names no stored plan is rejected with `ERR_INSURANCE_PLAN_NOT_FOUND`. Patient lists may be filtered by `insurance_plan_id`, by `state_code` and by `auto_reorder_enabled`.

Capturing a prescription is the patient's own act (an administrator may act on their behalf). The capture names the owning `customer_id`, the prescribed SKU as `product_id`, and a `capture_mode` of `UPLOAD`, `DOCTOR_LOOKUP` or `SELF_REPORT`. The clinical content is `od_sphere` and `os_sphere` — the right-eye and left-eye powers — together with the prescribed `base_curve` and `diameter`. The commercial content is `boxes_authorized_total`, the total number of boxes the prescription authorises across its whole life, which must be at least 1. The temporal content is `issue_date`, the inclusive start of the validity interval, and `expiry_date`, its **exclusive** end; `expiry_date` must fall strictly after `issue_date`, and a capture that violates this is rejected with `ERR_EXPIRY_BEFORE_ISSUE`.

Each capture mode carries its own evidence obligation, checked both at capture time and again at submit. An `UPLOAD` capture must carry a `document_reference` naming the scan, or the request fails with `ERR_CAPTURE_MODE_REQUIRES_DOCUMENT`. A `DOCTOR_LOOKUP` capture must carry a `prescriber_id`, or the request fails with `ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER`; a `prescriber_id` that names no stored provider yields `ERR_PRESCRIBER_NOT_FOUND`. A `SELF_REPORT` capture must carry a `self_reported_prescriber_name` in free text, or the request fails with `ERR_SELF_REPORT_REQUIRES_NAME`. The optional `supersedes_prescription_id` is a self-reference to the prescription this one replaces; its role is described in §3.3.

A newly captured prescription is in `DRAFT`. Its `status` moves through `DRAFT`, `PENDING_VERIFICATION`, `CORRECTION_PENDING` and `VERIFIED_ACTIVE`, and terminates in either `INVALIDATED` or `EXPIRED`. It also carries two derived counters: `boxes_consumed`, the running box ledger described in §2.7, and `verification_rounds`, the number of verification contacts sent on its behalf, both starting at zero. Prescriptions may be listed filtered by `customer_id`, `prescriber_id`, `product_id`, `status`, and by `supersedes_prescription_id` so that a supersession chain can be walked.

### 3.3. The Submit Fork and Passive Verification Rounds

Submitting a prescription is declared only for a prescription in `DRAFT`; attempting it from any other state yields `ERR_INVALID_STATE_TRANSITION`. In every case the submitted prescription's `expiry_date` must fall strictly after the current logical date, and a lapsed prescription is refused with `ERR_PRESCRIPTION_EXPIRED`.

Submission forks on `capture_mode`, and the two branches differ substantially.

**The upload branch.** When `capture_mode` is `UPLOAD` and `document_reference` is present, the document itself is the evidence and the prescription goes straight from `DRAFT` to `VERIFIED_ACTIVE`. Before it does, an overlap check runs: no other prescription of the same customer in `VERIFIED_ACTIVE` or `PENDING_VERIFICATION` may have a half-open validity interval that overlaps this one's interval from `issue_date` inclusive to `expiry_date` exclusive. Intervals that merely touch — where one prescription's `expiry_date` equals the other's `issue_date` — do not overlap and are permitted. An overlap is rejected with `ERR_PRESCRIPTION_INTERVAL_OVERLAP` unless `supersedes_prescription_id` names precisely the overlapping prescription, which is the legitimate case of a patient replacing an old prescription mid-interval. A successful upload submit appends a compliance event of type `RX_SUBMITTED` with the detail `upload accepted`. When `supersedes_prescription_id` is set, the superseded prescription is driven to `INVALIDATED` and every one of its `ACTIVE` auto-reorder schedules moves to `CANCELLED`, after which the affected customer's `active_schedule_count` and `auto_reorder_enabled` are reconciled.

**The passive branch.** When `capture_mode` is `DOCTOR_LOOKUP` — which requires `prescriber_id` — or `SELF_REPORT` — which requires `self_reported_prescriber_name` — the prescription moves from `DRAFT` to `PENDING_VERIFICATION` and awaits the prescriber. This submit appends a compliance event of type `RX_SUBMITTED` with the detail `awaiting prescriber verification`, and it does nothing else: in particular it does not invalidate the prescription named by `supersedes_prescription_id` and does not cancel that prescription's schedules. The supersession cascade belongs to the upload branch alone.

Once a prescription sits in `PENDING_VERIFICATION`, a compliance officer opens a verification round by naming the `prescriber_id` to contact. This is a self-loop on `PENDING_VERIFICATION` — the prescription's `status` does not change — and it is also the way a prescription in `CORRECTION_PENDING` returns to `PENDING_VERIFICATION` for another attempt. Both variants of the round-opening are governed by the same four gates, evaluated in the order given in §2.10: the named provider's `status` must be `ACTIVE`, or the contact is refused with `ERR_PRESCRIBER_SUSPENDED`; the same provider must not already have been contacted about the same prescription inside the four-business-hour cooldown window, or the contact is refused with `ERR_PRESCRIBER_CONTACT_COOLDOWN` at HTTP 429; the provider must currently hold fewer than three verification requests in `SENT` status counted across every prescription in the system, or the contact is refused with `ERR_PRESCRIBER_REQUEST_CAPACITY`; and the prescription's `verification_rounds` must be strictly less than the round cap of three, or the contact is refused with `ERR_MAX_VERIFICATION_ROUNDS`.

The cooldown window is computed by advancing four business hours from the earlier contact's send instant using the business-hour walk of §2.5, and the window is **closed** at that end: a new contact attempted at an instant that is at or before the computed cooldown end is blocked, and only an instant strictly after it is allowed.

A successful round creates a **verification request**. It records the `prescription_id` being verified and the `prescriber_id` receiving the contact, snapshots the provider's `contact_channel` into its own `channel`, and stamps `sent_at` from the logical clock. Its `round_number` is a one-based index within the prescription, set to the prescription's `verification_rounds` plus one, and the prescription's `verification_rounds` is then incremented. Opening a round appends a compliance event of type `REQUEST_SENT`. The request's `status` begins at `SENT` and ends in one of four terminal values — `CONFIRMED`, `CORRECTED`, `DENIED` or `PASSIVE_TIMEOUT` — and its `response_type` stays null until a provider actually answers, at which point it takes the value `CONFIRMED`, `CORRECTED` or `DENIED`. Verification requests may be listed filtered by `prescription_id`, `prescriber_id` and `status`.

The deadline is the heart of the mechanism. Each request's `passive_deadline_at` is computed by advancing a business-hour budget from `sent_at`: **eight** business hours when the receiving provider's `directory_verified` flag is true, and **twelve** business hours when it is false, because a prescriber the patient merely named deserves longer to object than one the directory confirmed. Silence past that instant is treated as agreement.

### 3.4. Prescriber Responses, the Verification Sweep and Expiry

A prescriber answers their own verification request, supplying a `response_type` and optionally a free-text `note`. The response is declared only for a request whose `status` is `SENT`, and the current logical time must be **strictly before** `passive_deadline_at`; a response at or after the deadline is refused with `ERR_VERIFICATION_WINDOW_CLOSED`. The responding provider's identity must equal the request's `prescriber_id`, or the attempt is refused with `ERR_IDENTITY_MISMATCH`. The three branches fan out very differently and each is specified in full.

**Confirmation.** A `CONFIRMED` response sets the request's `status` and `response_type` both to `CONFIRMED` and promotes the prescription from `PENDING_VERIFICATION` to `VERIFIED_ACTIVE`. A compliance event of type `RESPONSE_RECEIVED` is appended. Every order against that prescription whose `verification_state` is `RX_PENDING` then moves to `RX_CLEARED`, processed in `created_at` ascending order, each of those orders contributing its own `RESPONSE_RECEIVED` compliance event with `subject_type` `Order`. The orders' `fulfillment_state` is untouched.

**Correction.** A `CORRECTED` response requires both `corrected_od_sphere` and `corrected_os_sphere` in the payload; absent either, the request is malformed. It sets the request's `status` and `response_type` both to `CORRECTED`, moves the prescription from `PENDING_VERIFICATION` to `CORRECTION_PENDING`, and overwrites the prescription's `od_sphere` and `os_sphere` with the corrected values. A `RESPONSE_RECEIVED` compliance event is appended carrying the detail `parameters corrected`. No order changes state on this branch — a corrected prescription is not yet verified, and the compliance desk must open a further round to get it confirmed.

**Denial.** A `DENIED` response sets the request's `status` and `response_type` both to `DENIED` and drives the prescription from `PENDING_VERIFICATION` to the terminal `INVALIDATED`, appending an `RX_INVALIDATED` compliance event. Four further effects follow, and all four are part of the same operation. A reorder hold is created for the prescription's customer with `reason` `PRESCRIBER_DENIED`, `status` `OPEN`, and `opened_by_user_id` set to the literal string `system`. Every order against the prescription whose `fulfillment_state` is `PENDING` moves from `RX_PENDING` to the terminal `RX_BLOCKED`, each appending an `ORDER_BLOCKED` compliance event. Every `ACTIVE` auto-reorder schedule on the prescription moves to `PAUSED` with `pause_reason` `HOLD_OPEN`, processed in `created_at` ascending order, each appending a `SCHEDULE_PAUSED` compliance event. Finally the customer's `open_hold_count`, `active_schedule_count` and `auto_reorder_enabled` are all reconciled.

When a correction round stalls and nobody will confirm, a compliance officer may invalidate the prescription manually, supplying a `reason`. This is declared only for a prescription in `CORRECTION_PENDING`; from any other state it yields `ERR_INVALID_STATE_TRANSITION`. It appends an `RX_INVALIDATED` compliance event, opens a reorder hold with `reason` `MANUAL` in `OPEN` status, and recomputes the customer's `open_hold_count` and `auto_reorder_enabled`.

Silence is handled by the **verification sweep**, which a compliance officer runs against the logical clock. The sweep performs two steps in a fixed order inside one call, and the ordering matters because a single sweep can both promote a prescription and then expire it.

*Step one — passive promotion.* Every verification request still in `SENT` whose `passive_deadline_at` has been reached, meaning the current logical time is at or after it, moves to the terminal `PASSIVE_TIMEOUT` with `response_type` left null. Its prescription is promoted from `PENDING_VERIFICATION` to `VERIFIED_ACTIVE`, a `PASSIVE_PROMOTED` compliance event is appended, and every order against that prescription whose `verification_state` is `RX_PENDING` moves to `RX_CLEARED` in `created_at` ascending order, each appending its own `PASSIVE_PROMOTED` compliance event with `subject_type` `Order`.

*Step two — expiry.* Every prescription then in `VERIFIED_ACTIVE` whose `expiry_date` is at or before the current logical date moves to the terminal `EXPIRED`. An `RX_EXPIRED` compliance event is appended. A reorder hold is opened with `reason` `PRESCRIPTION_EXPIRED` in `OPEN` status and `opened_by_user_id` set to `system`. Every `ACTIVE` schedule on that prescription moves to `PAUSED` with `pause_reason` `HOLD_OPEN`. Every order against that prescription whose `verification_state` is `RX_CLEARED` and whose `fulfillment_state` is `PENDING` moves to `RX_BLOCKED`, appending an `ORDER_BLOCKED` compliance event carrying the detail `prescription expired`. The affected customers' `open_hold_count`, `active_schedule_count` and `auto_reorder_enabled` are then reconciled.

The sweep returns a summary rather than a resource: `promoted_prescription_ids` lists the prescriptions promoted in step one, `timed_out_request_ids` the verification requests that timed out, `expired_prescription_ids` the prescriptions expired in step two, and `holds_opened_count` and `schedules_paused_count` the totals across both steps.

### 3.5. Ordering Boxes: Authorisation, Pricing and Clearance

An order is placed against a prescription by the patient themselves, by a warehouse operator, or by an administrator. The payload names the `customer_id`, the authorising `prescription_id`, the `ordered_product_id` the customer asked for, and the split of quantity across eyes: `boxes_od` for the right eye and `boxes_os` for the left, each of which must be zero or greater, with the sum of the two being at least 1. An optional `itemized_receipt_reference` may be attached at order time, and doing so matters later for reimbursement, as §3.9 explains.

Three gates guard placement, in the order of §2.10. The prescription must not be `INVALIDATED`, or the order is refused with `ERR_PRESCRIPTION_INVALIDATED`. The ordered product must not be `INACTIVE`, or the order is refused with `ERR_PRODUCT_INACTIVE`. And the box ledger must have room: the prescription's `boxes_consumed` plus the requested `boxes_od` plus `boxes_os` must not exceed its `boxes_authorized_total`, or the order is refused with `ERR_BOX_AUTHORIZATION_EXCEEDED`. A prescription whose `expiry_date` is at or before the current logical date, or whose `status` is already `EXPIRED`, cannot be ordered against at all and yields `ERR_PRESCRIPTION_EXPIRED`.

Order creation snapshots and prices in one step. The ordered product's `unit_price_cents` and `lenses_per_box` are copied onto the order as `unit_price_cents` and `lenses_per_box_at_capture`, and `fulfilled_product_id` is initialised to the same value as `ordered_product_id`. Pricing then proceeds in strict order. Total boxes is `boxes_od` plus `boxes_os`. `subtotal_cents` is the snapshotted `unit_price_cents` multiplied by total boxes. `shipping_cents` is zero when `subtotal_cents` has reached the free-shipping threshold of 5,000 cents — fifty dollars, and the comparison is inclusive, so a subtotal of exactly 5,000 cents ships free — and is otherwise the flat standard charge of 695 cents. `total_cents` is `subtotal_cents` plus `shipping_cents`. Because the price came from a snapshot, later repricing of the product leaves every existing order's money untouched.

A new order carries two independent lifecycle dimensions. Its `verification_state` is seeded from the prescription: `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and `RX_PENDING` otherwise. Its `fulfillment_state` begins at `PENDING`. The verification dimension takes the values `RX_PENDING`, `RX_CLEARED` and the terminal `RX_BLOCKED`; the fulfilment dimension takes `PENDING`, `SHIPPED` and the terminal values `DELIVERED` and `CANCELLED`. Neither dimension's transitions ever alter the other: clearance never ships an order, and shipping never re-clears one. Order lists may be filtered by `customer_id`, `prescription_id`, `ordered_product_id`, `fulfilled_product_id` and, independently, by `verification_state` and `fulfillment_state`.

Placing an order also moves the ledgers forward: the prescription's `boxes_consumed` grows by the ordered boxes, and the customer's `lifetime_charged_cents` and `net_cash_position_cents` are reconciled.

An order also carries fields it does not yet use at creation: `substitution_type` starts at `NONE`, `parameter_deviation_index` starts at 0.00, `fulfilled_od_sphere` and `fulfilled_os_sphere` start null, `recall_flagged` starts false, and `cancellation_reason`, `shipped_at` and `delivered_at` start null. Each is populated by a later workflow described below.

### 3.6. Substitution Within the Equivalence Graph

When the exact SKU a patient ordered is not on the shelf, a warehouse operator may swap in an equivalent. The request names the `substitute_product_id` and, as §2.9 requires, carries `expected_order_version`; it may also carry `patient_consent`. Substitution is deliberately **price-neutral**: it sets `fulfilled_product_id`, `substitution_type`, `parameter_deviation_index`, `fulfilled_od_sphere` and `fulfilled_os_sphere`, appends a `SUBSTITUTION_APPLIED` compliance event, and increments the order's `version`, while leaving `unit_price_cents`, `subtotal_cents`, `shipping_cents` and `total_cents` exactly as they were.

The clinical gate is the **parameter deviation index**, a weighted fitting distance between what the prescription specified and what will actually be dispensed. It is computed entirely in integer hundredths, so that a boundary case decided at exactly one half or exactly one whole unit is decided the same way every time:

1. Convert any decimal quantity to integer hundredths by multiplying it by one hundred and rounding half up to a whole number.
2. Determine what will actually be dispensed. `fulfilled_od_sphere` is the multiple of the substitute product's `sphere_step` nearest to the prescription's `od_sphere`; where two multiples are exactly equidistant, the tie resolves away from zero, that is toward the stronger power. `fulfilled_os_sphere` is derived from `os_sphere` by the same rule.
3. Sum four weighted absolute differences, each taken between the two values expressed in integer hundredths: the difference between the prescription's `base_curve` and the substitute product's `base_curve`, weighted by four; the difference between the prescription's `diameter` and the substitute product's `diameter`, weighted by two; the difference between the prescription's `od_sphere` and the dispensed `fulfilled_od_sphere`, weighted by one; and the difference between the prescription's `os_sphere` and the dispensed `fulfilled_os_sphere`, also weighted by one. Base curve therefore matters twice as much as diameter and four times as much as either sphere.
4. Divide that weighted sum by one hundred to obtain `parameter_deviation_index`, presented with two decimal places.

The index then decides the outcome across three bands. An index of **at most 0.50** auto-approves: the swap proceeds without consent. An index **above 0.50 and at most 1.00** sits in the consent band: the swap proceeds only when the payload carries `patient_consent` set to true, and otherwise is refused with `ERR_CONSENT_REQUIRED` at HTTP 422. An index **above 1.00** is clinically unacceptable and the swap is refused outright with `ERR_PARAMETER_DEVIATION_EXCEEDED` at HTTP 422, regardless of any consent the patient may have given. Consent is also required — irrespective of where the index falls — when the governing equivalence mapping has `requires_patient_consent` set true, which is always the case for `MATERIAL_ONLY` relationships; absent consent, that too yields `ERR_CONSENT_REQUIRED`.

Note the evaluation order, which is unusual and deliberate: the deviation ceiling is checked first, then the consent requirement, and only then whether a usable mapping exists at all. A substitution whose index exceeds 1.00 therefore reports `ERR_PARAMETER_DEVIATION_EXCEEDED` even when no `ACTIVE` lens equivalence maps the ordered product to the requested substitute. Where the index and consent both pass, the mapping requirement bites: an `ACTIVE` mapping whose `from_product_id` is the order's ordered product and whose `to_product_id` is the requested substitute must exist, or the request is refused with `ERR_NO_EQUIVALENCE_MAPPING` at HTTP 422. `RETIRED` mappings do not count. After that, the substitute product must not be `INACTIVE`, or the request is refused with `ERR_PRODUCT_INACTIVE`. Substitution is also refused with `ERR_PRESCRIPTION_INVALIDATED` when the order's prescription has been invalidated.

`substitution_type` records what kind of swap occurred. It stays `NONE` while no substitution has been applied. Once one is applied, it becomes `PARAMETER_ROUNDED` when the substitute product's `sphere_step` forced `fulfilled_od_sphere` or `fulfilled_os_sphere` away from the prescribed power, and `BRAND_EQUIVALENT` otherwise — that is, when both eyes are dispensed at exactly the prescribed powers and only the brand or material changed.

### 3.7. Fulfillment, Reorder Holds and the Auto-Reorder Engine

Shipping is the point where the two order dimensions meet. A warehouse operator may advance an order from `PENDING` to `SHIPPED` only when its `verification_state` is `RX_CLEARED` — an order still `RX_PENDING` or already `RX_BLOCKED` cannot ship, and the attempt is reported as an undeclared transition — and only when the order's customer has no reorder hold in `OPEN` status, which is reported specifically as `ERR_HOLD_OPEN_BLOCKS_ACTION`. Shipping stamps `shipped_at` from the logical clock and leaves `verification_state` untouched. Delivery then advances `SHIPPED` to the terminal `DELIVERED`, requires `shipped_at` to be present, and stamps `delivered_at` from the logical clock; `delivered_at` is what opens the reimbursement claim window. An order whose prescription has been invalidated cannot be shipped and yields `ERR_PRESCRIPTION_INVALIDATED`.

Cancellation is available while an order is still `PENDING` and is a full **compensating** operation, reversing every forward effect of placement. The caller — the patient, a compliance officer or an administrator — supplies a `cancellation_reason` of `CUSTOMER_REQUEST`, `DISPUTE_UPHELD`, `PRESCRIBER_DENIED` or `RX_EXPIRED`, which is recorded on the order as `fulfillment_state` moves to the terminal `CANCELLED`. The prescription's `boxes_consumed` is reduced by that order's `boxes_od` plus `boxes_os`, freeing the authorisation for reuse. The customer's `lifetime_charged_cents` and `net_cash_position_cents` are reconciled. Every reimbursement claim on the order whose `status` is `DRAFT`, `GENERATED` or `SUBMITTED` is voided, with `voided_reason` `CUSTOMER_REQUEST`; for those that had already reached `GENERATED` or `SUBMITTED`, voiding releases the plan-year allowance they had consumed. An `ORDER_CANCELLED` compliance event is appended.

**Reorder holds** are the compliance brake on the whole fulfilment pipeline. A hold names the held `customer_id`, the `prescription_id` that triggered it, and a `reason` of `PRESCRIBER_DENIED`, `PRESCRIPTION_EXPIRED`, `DISPUTE_UPHELD` or `MANUAL`. Opening a hold manually records the acting `X-User-ID` in `opened_by_user_id`, increments the customer's `open_hold_count`, recomputes `auto_reorder_enabled`, and appends a `HOLD_OPENED` compliance event. Holds opened by a cascade record `system` instead. A hold's `status` runs from `OPEN` to one of the terminal values `RELEASED` or `ESCALATED`, and holds may be listed filtered by `customer_id`, `prescription_id`, `reason` and `status`.

Releasing a hold has three gates, evaluated in the §2.10 order: the releasing `X-User-ID` must differ from `opened_by_user_id`, or the release is refused with `ERR_SEGREGATION_OF_DUTIES`; the prescription's `status` must be `VERIFIED_ACTIVE`, or the release is refused with `ERR_PRESCRIPTION_NOT_VERIFIED`; and no prescriber dispute on the same prescription may be in `OPEN` status, or the release is refused with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`. A release records `released_by_user_id`, appends a `HOLD_RELEASED` compliance event, and recomputes the customer's `open_hold_count` and `auto_reorder_enabled`. An optional `note` may accompany the release. Alternatively a compliance officer may escalate the hold instead of releasing it, supplying an `escalated_reason` that is recorded on the row; escalation moves the hold to `ESCALATED`, appends a `HOLD_ESCALATED` compliance event, and — because `ESCALATED` is no longer `OPEN` — also decrements `open_hold_count` and recomputes `auto_reorder_enabled`, so escalation clears the fulfilment block just as release does.

An **auto-reorder schedule** is a recurring shipment plan. It is created by the patient against a `customer_id`, a `prescription_id` whose `status` must be `VERIFIED_ACTIVE` (or the request is refused with `ERR_PRESCRIPTION_NOT_VERIFIED`), a `product_id` that must not be `INACTIVE` (or `ERR_PRODUCT_INACTIVE`), a `boxes_per_run` of at least 1 giving the boxes shipped per eye-pair each run, and an `anchor_date` from which the cadence counts. The `cadence_basis` selects between two variants and defaults to `NOMINAL`; choosing `USAGE_ADJUSTED` requires the customer to supply `observed_days_per_box`, the number of days a box actually lasts them.

The interval is derived as follows. First establish how many days one lens covers, from the product's `wear_schedule`: one day for `DAILY_DISPOSABLE`, fourteen days for `BIWEEKLY`, thirty days for `MONTHLY`. Under the `NOMINAL` variant, the supply this run represents is `boxes_per_run` multiplied by the product's `lenses_per_box` multiplied by the days one lens covers. Under the `USAGE_ADJUSTED` variant, the supply is instead `boxes_per_run` multiplied by the reported `observed_days_per_box`, ignoring the wear schedule entirely. `cadence_days` is then that supply figure reduced by a fixed reorder lead time of five days, but never allowed below a floor of fourteen days — so a schedule whose raw supply is sixteen days lands on the floor rather than on eleven. `next_run_at` is the `anchor_date` advanced by `cadence_days`, at 08:00 UTC on that date. Creating a schedule increments the customer's `active_schedule_count` and recomputes `auto_reorder_enabled`.

A schedule's `status` is `ACTIVE`, `PAUSED` or the terminal `CANCELLED`, and it also carries `consecutive_skip_count`, starting at zero, and `pause_reason`, which is populated only while paused. The `ACTIVE`-`PAUSED` loop can be traversed repeatedly. A patient pausing their own schedule moves it from `ACTIVE` to `PAUSED` with `pause_reason` `CUSTOMER_REQUEST` and recomputes `active_schedule_count` and `auto_reorder_enabled`. Resuming moves it from `PAUSED` back to `ACTIVE`, but only when the customer has no hold in `OPEN` status — otherwise `ERR_HOLD_OPEN_BLOCKS_ACTION` — and only when the prescription's `status` is `VERIFIED_ACTIVE` — otherwise `ERR_PRESCRIPTION_NOT_VERIFIED`; a resume clears `pause_reason`, resets `consecutive_skip_count` to zero, and recomputes the customer's counters. Cancellation is declared from `PAUSED` only and moves the schedule to the terminal `CANCELLED`, recomputing the customer's counters. A schedule is also cancelled from `ACTIVE` as a consequence of a superseding upload submit, as §3.3 describes. Schedules may be listed filtered by `customer_id`, `prescription_id`, `product_id` and `status`.

The **auto-reorder run** is the deferred-action sweep that actually ships subscriptions. A warehouse operator triggers it, and it processes every `ACTIVE` schedule whose `next_run_at` has arrived relative to the logical clock, in ascending `next_run_at` order and, where two schedules are due at the same instant, in ascending `created_at` order. For each due schedule, an order is created and shipped when three conditions hold: the prescription is `VERIFIED_ACTIVE` and unexpired, the customer has no hold in `OPEN` status, and the prescription's remaining box authorisation covers the schedule's `boxes_per_run`. When any of those three fails, that schedule is **skipped rather than erroring** — the run still returns HTTP 200 — and its `consecutive_skip_count` is incremented; once that counter reaches the limit of two consecutive skips, the schedule moves from `ACTIVE` to `PAUSED` with `pause_reason` `SKIP_LIMIT` and a `SCHEDULE_PAUSED` compliance event is appended. On both the shipping and the skipping path, `next_run_at` is advanced by `cadence_days` and the affected customer's ledgers are reconciled. The run reports `run_at` as the logical instant it executed, plus `shipped_order_ids`, `skipped_schedule_ids` and `paused_schedule_ids`.

### 3.8. Returns, Proration and Two-Person Settlement

A return is opened by the patient against an `order_id` they own, naming their own `customer_id` and a `reason` of `TORN_LENS`, `PRESCRIPTION_CHANGE` or `WRONG_PARAMETER`. The physical content of the return is described by `unopened_boxes`, the count of fully unopened boxes coming back, defaulting to zero; `opened_box_used_counts`, an array with one element per opened box giving the lenses already used out of that box, defaulting to an empty array; and `torn_lens_count`, the number of lenses reported torn, which is required when `reason` is `TORN_LENS`. Quantities are checked against what the order actually shipped: `unopened_boxes` plus the length of `opened_box_used_counts` may not exceed the order's `boxes_od` plus `boxes_os`, no element of `opened_box_used_counts` may exceed the order's `lenses_per_box_at_capture`, and `torn_lens_count` may not exceed the total lenses shipped. Any of those violations is refused with `ERR_RETURN_QUANTITY_EXCEEDS_ORDER` at HTTP 422. Negative quantities never reach this check, being caught earlier as out-of-range values.

The `reason` drives everything downstream. It selects the `settlement_mode` — the rounding granularity variant — and it selects the `settlement_channel`. `PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`, `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects `NO_PRORATION`. The channel is `STORE_CREDIT` when `reason` is `TORN_LENS` and `CASH_REFUND` for the other two reasons — a torn lens is a replacement matter, not a refund matter. Creating the return computes `settlement_mode` together with a **preview** of `settlement_cents` and `settlement_channel` without moving any money.

The settlement figure is prorated from the order's snapshots — its `unit_price_cents` as the per-box value and its `lenses_per_box_at_capture` as the lens count per box — and never from the product's current values. Under both prorating variants, the unopened component is `unopened_boxes` multiplied by the per-box value, and the opened component values each opened box by the lenses left unused in it, as a fraction of a whole box. The two variants differ only in where the rounding happens, and that difference is enough to shift the same physical return by a cent:

- Under `PER_BOX_ROUNDED`, each opened box is valued independently as the per-box value multiplied by the unused lenses in that box divided by the lenses per box, **rounded half up to a whole cent for that box**, and those per-box amounts are then added together.
- Under `POOLED_ROUNDED`, the unused lenses across all opened boxes are added together first, that total is multiplied by the per-box value and divided by the lenses per box **exactly**, and the single resulting amount is rounded half up to a whole cent once.

For both prorating variants, `settlement_cents` is the unopened component plus the opened component. Under `NO_PRORATION`, no box residue is considered at all: the candidate figure is `torn_lens_count` multiplied by the per-box value, divided by the lenses per box and rounded half up to a whole cent, and `settlement_cents` is whichever is smaller — that candidate figure, or a cap equal to twenty percent of the order's `total_cents` with any fraction of a cent discarded downward.

Settlement itself is a two-person workflow. A return's `status` starts at `SUBMITTED` and ends in `REJECTED` or `SETTLED`. A compliance officer approves it, which is declared only when the order's `fulfillment_state` is `SHIPPED` or `DELIVERED`; approval records `approved_by_user_id` and **freezes** `settlement_mode` and `settlement_cents` at the computed values, so later reference-data edits cannot move an approved figure. Alternatively the officer rejects it from `SUBMITTED`, supplying a `rejection_reason` that is recorded on the row; a rejection moves no money.

A different compliance officer then settles the approved return. The settling `X-User-ID` must differ from `approved_by_user_id`, or the settlement is refused with `ERR_SEGREGATION_OF_DUTIES`. The frozen `settlement_cents` added to the sum of prior settled settlements on the same order must not exceed the order's `total_cents`, or the settlement is refused with `ERR_REFUND_EXCEEDS_CAPTURE` — the platform never refunds more than it captured. Settlement records `settled_by_user_id`, and this is where money actually moves: a `STORE_CREDIT` settlement credits the customer's `store_credit_cents`, while a `CASH_REFUND` settlement increases `lifetime_refunded_cents`, and either way `net_cash_position_cents` is then reconciled. Settlement also reaches into any reimbursement paperwork still in progress: `refund_offset_cents` is set on every claim on that order whose `status` is `DRAFT`, so a claim generated afterwards cannot ask the plan to reimburse money the platform has already returned. Return requests may be listed filtered by `order_id`, `customer_id`, `reason` and `status`.

### 3.9. Reimbursement Packets, Prescriber Disputes and Compensating Cascades

Out-of-network reimbursement begins with the patient opening a claim naming the `order_id`, their `customer_id`, and the `insurance_plan_id` the claim will be priced against. The plan must not be `RETIRED`, or the claim is refused with `ERR_PLAN_RETIRED`, and its `network_status` must be `OUT_OF_NETWORK` rather than `IN_NETWORK`, or the claim is refused with `ERR_PLAN_NOT_OUT_OF_NETWORK` at HTTP 422 — in-network care is billed by the provider, not reimbursed to the member. The claim is created in `DRAFT` with every money field null except `refund_offset_cents`, which is seeded from the settled returns already recorded against the order. A claim's `status` runs `DRAFT`, `GENERATED`, `SUBMITTED` and the terminal `VOIDED`; claims may be listed filtered by `order_id`, `customer_id`, `insurance_plan_id` and `status`.

Generating the packet is the compliance desk's job and is declared only from `DRAFT`. The order's `fulfillment_state` must be `DELIVERED`. The plan must still be `ACTIVE` and `OUT_OF_NETWORK`. When the plan's `requires_itemized_receipt` is true, the order must carry an `itemized_receipt_reference`, or generation is refused with `ERR_ITEMIZED_RECEIPT_REQUIRED` at HTTP 422. The current logical date must not be more than the plan's `claim_window_days` past the order's `delivered_at`, or generation is refused with `ERR_CLAIM_WINDOW_CLOSED`. And the remaining plan-year allowance must be strictly greater than zero, or generation is refused with `ERR_ALLOWANCE_EXHAUSTED`.

The money is then computed in a **fixed eight-step order**, and the order is load-bearing because the processing-fee tier is keyed on the seventh step's result rather than on the order subtotal or on the final figure. Any reordering of the steps produces a different fee on the same order.

1. Gross spend is the order's `subtotal_cents`, plus the order's `shipping_cents` when the plan's `covers_shipping` is true and plus nothing when it is false.
2. `refund_offset_cents` is the sum of `settlement_cents` over the return requests on this order whose `status` is `SETTLED`.
3. `base_eligible_cents` is gross spend less `refund_offset_cents`, floored at zero.
4. Remaining allowance is the plan's `annual_allowance_cents` less the customer's `allowance_used_cents`, floored at zero.
5. `applied_allowance_cents` is whichever is smaller, `base_eligible_cents` or that remaining allowance.
6. `coinsurance_cents` is `base_eligible_cents` less `applied_allowance_cents`, multiplied by the plan's `coinsurance_rate`, rounded half up to a whole cent.
7. `pre_fee_subtotal_cents` is `applied_allowance_cents` plus `coinsurance_cents`.
8. `processing_fee_cents` is keyed on `pre_fee_subtotal_cents` across three tiers: nothing at all when it is at most 5,000 cents, 250 cents when it is above 5,000 cents and at most 15,000 cents, and 500 cents above that. `reimbursable_cents`, the final figure the plan will reimburse, is `pre_fee_subtotal_cents` less `processing_fee_cents`, floored at zero.

Generation also mints a `packet_reference`, the paperwork identifier, and increases the customer's `allowance_used_cents` by `applied_allowance_cents` — reconciled, as §2.7 requires, from the live claim rows rather than incremented blindly.

Submission moves a claim from `GENERATED` to `SUBMITTED`. It requires `packet_reference` to be present and the current logical date to still fall within the plan's `claim_window_days` of `delivered_at`, failing which it is refused with `ERR_CLAIM_WINDOW_CLOSED`. It stamps `submitted_at` from the logical clock and leaves allowance consumption unchanged. Voiding a claim directly is declared only from `GENERATED`; the officer supplies a `voided_reason` of `DISPUTE_UPHELD`, `CUSTOMER_REQUEST` or `PLAN_RETIRED`, the customer's `allowance_used_cents` is decreased by the claim's `applied_allowance_cents` — releasing exactly what generation consumed — and a `CLAIM_VOIDED` compliance event is appended. A claim still in `DRAFT` is voided as a side effect of its order being cancelled, taking `voided_reason` `CUSTOMER_REQUEST`.

**Prescriber disputes** are the last and deepest mechanism. A provider files one against a `prescription_id` naming their own `prescriber_id`, with a `dispute_reason` of `NOT_MY_PATIENT`, `PARAMETERS_ALTERED` or `NEVER_ISSUED`, and — as §2.9 requires — an `expected_prescription_version` matching the prescription's current `version`. Filing appends a `DISPUTE_FILED` compliance event, and from that moment the dispute's existence in `OPEN` status blocks release of any reorder hold on the same prescription. A dispute's `status` is `OPEN` and then one of the terminal values `UPHELD` or `DISMISSED`; disputes may be listed filtered by `prescription_id`, `prescriber_id` and `status`.

Only a compliance officer or administrator resolves a dispute, supplying a `resolution` of `UPHELD` or `DISMISSED`. Both branches set the dispute's `resolution` and `resolved_by_user_id` and append a `DISPUTE_RESOLVED` compliance event, and both are declared only from `OPEN`.

A `DISMISSED` resolution is otherwise a no-op: the prescription, its orders and its claims are left exactly as they were, no hold is opened, no ledger is touched.

An `UPHELD` resolution is the widest cascade in the system, and every one of its effects is part of the same operation. The prescription is driven from `VERIFIED_ACTIVE` to the terminal `INVALIDATED` and an `RX_INVALIDATED` compliance event is appended. Every order against that prescription whose `fulfillment_state` is `PENDING` is cancelled with `cancellation_reason` `DISPUTE_UPHELD`, processed in `created_at` ascending order, and each such cancellation applies the same compensating ledger work as a patient-initiated cancellation: the prescription's `boxes_consumed` is reduced by that order's boxes and the customer's charge and cash figures are reconciled. Every order against that prescription whose `fulfillment_state` is `SHIPPED` or `DELIVERED` cannot be cancelled — the lenses are already in the post — so instead its `recall_flagged` flag is set to true, marking it for physical recall. Every reimbursement claim on those cancelled or recall-flagged orders whose `status` is `DRAFT`, `GENERATED` or `SUBMITTED` is voided with `voided_reason` `DISPUTE_UPHELD`, each releasing its `applied_allowance_cents` back to the allowance ledger and appending a `CLAIM_VOIDED` compliance event. Finally the affected customer's `allowance_used_cents`, `lifetime_charged_cents` and `net_cash_position_cents` are all reconciled, so that INV_MONEY, INV_ALLOWANCE and INV_BOXES all hold again the instant the response is returned.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or that add a new distinct resource to a collection, return `201 Created`. Every other operation — reads, state transitions, sweeps, and the logical-clock write — returns `200 OK`. Error responses carry the status code listed in §5 alongside the error identifier in the envelope's `data` object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| GET | `/_clock` | Read the current logical clock | PlatformAdmin, ComplianceOfficer, FulfillmentOperator |
| POST | `/insurance-plans` | Register a vision plan | PlatformAdmin |
| GET | `/insurance-plans/{id}` | Read one vision plan | PlatformAdmin, ComplianceOfficer, Customer |
| GET | `/insurance-plans` | Paginated vision plan list | PlatformAdmin, ComplianceOfficer |
| POST | `/insurance-plans/{id}/retire` | Retire a vision plan | PlatformAdmin |
| POST | `/products` | Register a lens SKU | PlatformAdmin |
| GET | `/products/{id}` | Read one product | PlatformAdmin, ComplianceOfficer, FulfillmentOperator, Customer |
| GET | `/products` | Paginated product list | PlatformAdmin, ComplianceOfficer, FulfillmentOperator, Customer |
| POST | `/products/{id}/deactivate` | Deactivate a product | PlatformAdmin |
| POST | `/products/{id}/lens-equivalences` | Declare a directed substitution mapping from the path product | PlatformAdmin |
| GET | `/products/{id}/lens-equivalences` | List mappings touching the path product | PlatformAdmin, ComplianceOfficer, FulfillmentOperator |
| POST | `/prescribers` | Register a prescriber | PlatformAdmin |
| GET | `/prescribers/{id}` | Read one prescriber | PlatformAdmin, ComplianceOfficer, Prescriber |
| GET | `/prescribers` | Paginated prescriber list | PlatformAdmin, ComplianceOfficer |
| POST | `/prescribers/{id}/suspend` | Suspend a prescriber | PlatformAdmin |
| POST | `/customers` | Register a patient | PlatformAdmin |
| GET | `/customers/{id}` | Read one patient including every derived ledger field | PlatformAdmin, ComplianceOfficer, Customer |
| GET | `/customers` | Paginated patient list | PlatformAdmin, ComplianceOfficer |
| GET | `/customers/{id}/ledger` | Reconciled ledger view for one patient | PlatformAdmin, ComplianceOfficer, Customer |
| POST | `/prescriptions` | Capture a prescription in DRAFT | Customer, PlatformAdmin |
| GET | `/prescriptions/{id}` | Read one prescription including its version | PlatformAdmin, ComplianceOfficer, Customer, Prescriber |
| GET | `/prescriptions` | Paginated prescription list | PlatformAdmin, ComplianceOfficer, Customer, Prescriber |
| POST | `/prescriptions/{id}/submit` | Submit a prescription along the branching fork | Customer, PlatformAdmin |
| POST | `/prescriptions/{id}/verification-requests` | Open a passive verification round | ComplianceOfficer, PlatformAdmin |
| GET | `/prescriptions/{id}/compliance-events` | Append-only audit trail for the path prescription | PlatformAdmin, ComplianceOfficer |
| POST | `/prescriptions/{id}/invalidate` | Manually invalidate a stalled correction | ComplianceOfficer, PlatformAdmin |
| GET | `/verification-requests/{id}` | Read one verification request including its deadline | PlatformAdmin, ComplianceOfficer, Prescriber |
| GET | `/verification-requests` | Paginated verification request list | PlatformAdmin, ComplianceOfficer, Prescriber |
| POST | `/verification-requests/{id}/respond` | Prescriber response inside the passive window | Prescriber, PlatformAdmin |
| POST | `/compliance/verification-sweep` | Two-step promotion and expiry sweep | ComplianceOfficer, PlatformAdmin |
| POST | `/orders` | Place a boxes order against a prescription | Customer, FulfillmentOperator, PlatformAdmin |
| GET | `/orders/{id}` | Read one order including its version and both state dimensions | PlatformAdmin, ComplianceOfficer, FulfillmentOperator, Customer |
| GET | `/orders` | Paginated order list | PlatformAdmin, ComplianceOfficer, FulfillmentOperator, Customer |
| POST | `/orders/{id}/substitution` | Swap the fulfilled product under concurrency control | FulfillmentOperator, PlatformAdmin |
| POST | `/orders/{id}/ship` | Ship a cleared, unheld order | FulfillmentOperator, PlatformAdmin |
| POST | `/orders/{id}/deliver` | Mark an order delivered | FulfillmentOperator, PlatformAdmin |
| POST | `/orders/{id}/cancel` | Compensating cancellation of a pending order | Customer, ComplianceOfficer, PlatformAdmin |
| POST | `/reorder-holds` | Open a compliance hold manually | ComplianceOfficer, PlatformAdmin |
| GET | `/reorder-holds/{id}` | Read one hold | PlatformAdmin, ComplianceOfficer, Customer |
| GET | `/reorder-holds` | Paginated hold list | PlatformAdmin, ComplianceOfficer, Customer |
| POST | `/reorder-holds/{id}/release` | Release a hold under segregation of duties | ComplianceOfficer, PlatformAdmin |
| POST | `/reorder-holds/{id}/escalate` | Escalate a hold instead of releasing it | ComplianceOfficer, PlatformAdmin |
| POST | `/auto-reorder-schedules` | Start a recurring shipment plan | Customer, PlatformAdmin |
| GET | `/auto-reorder-schedules/{id}` | Read one schedule including its cadence | PlatformAdmin, ComplianceOfficer, FulfillmentOperator, Customer |
| GET | `/auto-reorder-schedules` | Paginated schedule list | PlatformAdmin, ComplianceOfficer, FulfillmentOperator, Customer |
| POST | `/auto-reorder-schedules/{id}/pause` | Patient-initiated pause | Customer, PlatformAdmin |
| POST | `/auto-reorder-schedules/{id}/resume` | Resume a paused schedule | Customer, PlatformAdmin |
| POST | `/auto-reorder-schedules/{id}/cancel` | Terminal cancellation of a paused schedule | Customer, PlatformAdmin |
| POST | `/fulfillment/auto-reorder-run` | Deferred-action run of due schedules | FulfillmentOperator, PlatformAdmin |
| POST | `/return-requests` | Open a torn-lens or prescription-change return | Customer, PlatformAdmin |
| GET | `/return-requests/{id}` | Read one return request including its settlement figures | PlatformAdmin, ComplianceOfficer, Customer |
| GET | `/return-requests` | Paginated return list | PlatformAdmin, ComplianceOfficer, Customer |
| POST | `/return-requests/{id}/approve` | Approval step of the two-person return workflow | ComplianceOfficer, PlatformAdmin |
| POST | `/return-requests/{id}/reject` | Reject a return | ComplianceOfficer, PlatformAdmin |
| POST | `/return-requests/{id}/settle` | Settlement step of the two-person return workflow | ComplianceOfficer, PlatformAdmin |
| POST | `/reimbursement-claims` | Open an out-of-network reimbursement claim | Customer, PlatformAdmin |
| GET | `/reimbursement-claims/{id}` | Read one claim including all eight money steps | PlatformAdmin, ComplianceOfficer, Customer |
| GET | `/reimbursement-claims` | Paginated claim list | PlatformAdmin, ComplianceOfficer, Customer |
| POST | `/reimbursement-claims/{id}/generate` | Generate the packet and consume plan-year allowance | ComplianceOfficer, PlatformAdmin |
| POST | `/reimbursement-claims/{id}/submit` | Submit a generated packet inside the claim window | ComplianceOfficer, PlatformAdmin |
| POST | `/reimbursement-claims/{id}/void` | Compensating void of a claim | ComplianceOfficer, PlatformAdmin |
| POST | `/prescriber-disputes` | File a dispute under concurrency control | Prescriber, PlatformAdmin |
| GET | `/prescriber-disputes/{id}` | Read one dispute | PlatformAdmin, ComplianceOfficer, Prescriber |
| GET | `/prescriber-disputes` | Paginated dispute list | PlatformAdmin, ComplianceOfficer, Prescriber |
| POST | `/prescriber-disputes/{id}/resolve` | Resolve a dispute, upheld or dismissed | ComplianceOfficer, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_IDENTITY_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_PRESCRIPTION_VERSION` | 412 |
| `ERR_INSURANCE_PLAN_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_PRESCRIBER_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_VERIFICATION_REQUEST_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_REORDER_HOLD_NOT_FOUND` | 404 |
| `ERR_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_RETURN_REQUEST_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_LICENSE` | 409 |
| `ERR_EXPIRY_BEFORE_ISSUE` | 400 |
| `ERR_CAPTURE_MODE_REQUIRES_DOCUMENT` | 400 |
| `ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER` | 400 |
| `ERR_SELF_REPORT_REQUIRES_NAME` | 400 |
| `ERR_PRESCRIPTION_INTERVAL_OVERLAP` | 409 |
| `ERR_PRESCRIPTION_EXPIRED` | 409 |
| `ERR_PRESCRIPTION_NOT_VERIFIED` | 409 |
| `ERR_PRESCRIPTION_INVALIDATED` | 409 |
| `ERR_PRESCRIBER_SUSPENDED` | 409 |
| `ERR_VERIFICATION_WINDOW_CLOSED` | 409 |
| `ERR_PRESCRIBER_CONTACT_COOLDOWN` | 429 |
| `ERR_PRESCRIBER_REQUEST_CAPACITY` | 409 |
| `ERR_MAX_VERIFICATION_ROUNDS` | 409 |
| `ERR_PARAMETER_DEVIATION_EXCEEDED` | 422 |
| `ERR_CONSENT_REQUIRED` | 422 |
| `ERR_NO_EQUIVALENCE_MAPPING` | 422 |
| `ERR_PRODUCT_INACTIVE` | 409 |
| `ERR_OPEN_DISPUTE_BLOCKS_RELEASE` | 409 |
| `ERR_HOLD_OPEN_BLOCKS_ACTION` | 409 |
| `ERR_PLAN_RETIRED` | 409 |
| `ERR_PLAN_NOT_OUT_OF_NETWORK` | 422 |
| `ERR_ITEMIZED_RECEIPT_REQUIRED` | 422 |
| `ERR_CLAIM_WINDOW_CLOSED` | 409 |
| `ERR_ALLOWANCE_EXHAUSTED` | 409 |
| `ERR_BOX_AUTHORIZATION_EXCEEDED` | 409 |
| `ERR_RETURN_QUANTITY_EXCEEDS_ORDER` | 422 |
| `ERR_REFUND_EXCEEDS_CAPTURE` | 409 |
