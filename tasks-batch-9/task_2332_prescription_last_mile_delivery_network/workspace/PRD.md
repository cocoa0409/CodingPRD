# Prescription Last-Mile Delivery API — Product Requirements Document

## 1. Introduction

ScriptDrop operates the last mile between a dispensing pharmacy counter and a patient's front door. That mile is unusually unforgiving: a bag may contain refrigerated biologics that spoil after two hours out of a cold box, or a Schedule II controlled substance that may only be handed to a person whose government photo identification has been scanned, and the same bag is frequently paid for by three parties at once — the patient, the pharmacy, and a health plan that has funded a fixed subsidy pool for the benefit year. The courier who carries it, meanwhile, is a third party under HIPAA and must be told the least possible amount about the person receiving it.

This document specifies the API that runs that network. It governs the whole arc of a delivery: intake of a filled prescription bundle at the dispensing site, selection of a promised delivery interval and reservation of capacity inside it, deterministic routing to an on-demand or scheduled courier, physical custody handoff, door-step identity verification and proof-of-delivery capture, a bounded ladder of re-attempts, return of undelivered product to pharmacy stock, and finally the reconciliation of an exception into either a replacement shipment, a fee credit, or a denial. Every money figure in the system is carried in whole cents and every temporal rule reads a single logical clock, so the same sequence of requests always produces the same ledger.

Two design commitments shape almost every rule that follows. First, a delivery's physical custody and its money settlement are **independent dimensions** on the same record: a bag can be sitting in a patient's hands while its bill is still provisional, and its bill can be voided while the bag is still in a courier's trunk. Second, an operator who creates an exception — or who yanked a courier off the job — is never the operator who decides what the network owes for it; segregation of duties is enforced inside the operations role itself.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold across every endpoint: authentication, envelope shape, pagination, identity and versioning of resources, temporal conventions, money precision, cascade discipline, the order in which rules are evaluated, and the HIPAA minimisation profile. Every collection is mounted at the top level of the API — there is no ownership nesting in URL paths, and resources are linked by identifier fields carried in request bodies.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they are acting. A request whose `X-User-ID` header is absent or empty is rejected with `ERR_UNAUTHENTICATED` before routing, role resolution, or path existence are considered at all. The system recognises exactly five roles: `PharmacyOperator`, `Patient`, `Courier`, `NetworkOps`, and `PlanAdministrator`. When the resolved role does not appear in the addressed endpoint's authorised role list, the request is rejected with `ERR_UNAUTHORIZED`.

The acting role is resolved by locating `X-User-ID` among the stored identifiers of four entity collections — pharmacies, patients, couriers, and health plans. An identifier that matches none of them is treated as `NetworkOps`. This makes `X-User-ID` an ownership claim, not just an audit label:

- When `X-User-Role` is `PharmacyOperator`, `X-User-ID` is the `id` of the acting `Pharmacy`; ownership checks on any resource that references a `Pharmacy` compare the resource's `pharmacy_id` to `X-User-ID`. A pharmacy operator reaching an order or a delivery belonging to another dispensing site is rejected with `ERR_PHARMACY_SCOPE_VIOLATION`.
- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks compare the `patient_id` of the `PharmacyOrder` behind the addressed resource to `X-User-ID`, and a mismatch is `ERR_PATIENT_SCOPE_VIOLATION`.
- When `X-User-Role` is `Courier`, `X-User-ID` is the `id` of the acting `Courier`; ownership checks compare the addressed delivery's or assignment's `courier_id` to `X-User-ID`, and a mismatch is `ERR_COURIER_SCOPE_VIOLATION`.
- When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is the `id` of the acting `HealthPlan`; ownership checks compare the `health_plan_id` of the addressed grant pool, or of the `PharmacyOrder` behind the addressed delivery, to `X-User-ID`, and a mismatch is `ERR_PLAN_SCOPE_VIOLATION`.
- When `X-User-Role` is `NetworkOps`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow demands accountability — as `opened_by_ops_user_id` and `adjudicated_by_ops_user_id` on an `ExceptionCase`, and as `revoked_by_ops_user_id` on a `CourierAssignment` — but never compares it to any entity's `id`.

`PharmacyOperator` owns order intake, release for scheduling, window reservation, and physical return receipt. `Patient` has no operation of its own that a pharmacy operator cannot also perform on their behalf; the difference between the two roles is scope, not capability. `Courier` accepts and declines offers, takes custody, departs, records door-step runs, and toggles its own availability — but a courier may never read a delivery's full record, only the redacted projection described in §2.11, and only while it holds an assignment. `NetworkOps` owns reference data, routing, sweeps, settlement, and exception adjudication. `PlanAdministrator` is a read-heavy payer role that funds grant pools and audits the allocations drawn against them; it never touches custody, routing, or settlement, and never reads patient records directly.

Segregation of duties operates *inside* the `NetworkOps` role rather than between roles. Two distinct `X-User-ID` values are required to carry an exception from opening to adjudication: an operator who opened a case, or who revoked a courier assignment on that case's delivery, is barred from adjudicating it and receives `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of rows returned; it defaults to 10, may not be lower than 1, and may not exceed 100. The `offset` parameter skips rows from the front of the result; it defaults to 0 and may not be negative. A `limit` outside the range 1 to 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, every list is sorted by `created_at` ascending. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

Beyond pagination, each list accepts exact-match filters over its own columns, and every filter is optional. Grant pools filter by `health_plan_id`, `benefit_year`, and `status`. Capacity windows filter by `zone_id`, `courier_mode`, and `status`. Orders filter by `pharmacy_id`, `patient_id`, `health_plan_id`, and `status`. Deliveries filter by `order_id`, `window_id`, `courier_id`, `reship_of_delivery_id`, `custody_status`, and `settlement_status`. Courier assignments filter by `delivery_id`, `courier_id`, and `status`. Door-step attempts filter by `delivery_id`, `courier_id`, and `outcome`. Fee allocations filter by `delivery_id`, `plan_grant_id`, `variant`, and `status`. Exception cases filter by `delivery_id`, `reship_delivery_id`, `exception_type`, and `status`. Disclosure audit trails accept only `limit` and `offset`.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource carries an `id`: a server-minted UUID with no type prefix. Clients never supply it.

Most resources also carry a standard trio of system-managed fields:

- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written.
- `updated_at` (string) — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row.
- `version` (integer) — a counter that increments by one on every mutation of the row, including mutations the server performs on its own initiative as a cascade from a request addressed at some other resource.

Two collections are append-only records of something that already happened and therefore carry only `id` and `created_at`: a `DeliveryAttempt` and a `CourierDataDisclosure` have **no** `updated_at` and **no** `version`. Every other collection — health plans, grant pools, pharmacies, patients, delivery zones, capacity windows, orders, couriers, deliveries, courier assignments, fee allocations, and exception cases — carries all four.

Because so much of this system moves by cascade, the versioning rule deserves emphasis: when one request drives a change on a second or third resource, each of those resources independently refreshes its `updated_at` and increments its `version`. A single door-step attempt can therefore bump the version of the delivery, the courier, the capacity window, the courier assignment, the fee allocation, and the grant pool.

### 2.5. The Logical Clock, Timestamps and Interval Conventions

Every temporal rule in this specification reads one logical clock rather than wall time. The clock starts at `2026-08-01T00:00:00Z` and stays there until an operations-only capability moves it: that capability accepts a single `current_utc` instant and echoes back the `current_utc` now in force. Wherever the text below says "the clock", it means this value. Fields whose value is described as "the clock value at" a transition — `offered_at`, `responded_at`, `picked_up_at`, `attempted_at`, `disclosed_at`, `delivered_at` — are stamped from it.

A capacity window is a **half-open** interval: `window_start` is inclusive, `window_end` is exclusive, so a window that begins exactly when another ends is a distinct slot rather than a clash. A courier's committed time, by contrast, is treated as a **closed** interval padded on both ends (§3.4), which is why two windows that are legal for a zone can still be illegal for one courier.

A window is **after hours** when the UTC hour of its `window_start` is 20 or later, or earlier than 6. The boolean `is_after_hours` on the window records that determination, and it is what makes the after-hours fee line non-zero.

### 2.6. Two Independent Status Dimensions on Every Delivery

A `Delivery` row carries two enumerated status fields that advance independently of each other.

`custody_status` tracks physical possession of the bag and is one of `QUEUED`, `ASSIGNED`, `PICKED_UP`, `OUT_FOR_DELIVERY`, `ATTEMPT_FAILED`, `DELIVERED`, `RETURN_PENDING`, `RETURNED`, or `CANCELLED`. A new delivery begins at `QUEUED`; `DELIVERED`, `RETURNED`, and `CANCELLED` are terminal, and any operation whose allowed from-set excludes the current value is rejected with `ERR_INVALID_CUSTODY_STATE`.

`settlement_status` tracks the money and is one of `PROVISIONAL`, `FINALIZED`, `WAIVED`, or `VOIDED`. A new delivery begins at `PROVISIONAL`; `FINALIZED`, `WAIVED`, and `VOIDED` are terminal, and an operation that needs the money dimension still open is rejected with `ERR_INVALID_SETTLEMENT_STATE` when it is not. The independence is real and observable: a delivery that has reached `DELIVERED` stays `DELIVERED` forever while its settlement moves from `PROVISIONAL` to `FINALIZED`, and a delivery whose settlement has been `VOIDED` by a cold-chain breach can still be sitting at `RETURN_PENDING` awaiting a physical return.

Other enumerated lifecycles in the system are single-dimensional: `PharmacyOrder.status` is one of `INTAKE`, `READY`, `DISPATCHED`, `CLOSED`, or `RETURNED_TO_STOCK`; `Courier.status` is one of `OFFLINE`, `AVAILABLE`, `ON_ROUTE`, or `SUSPENDED`; `CourierAssignment.status` is one of `OFFERED`, `ACCEPTED`, `DECLINED`, `EXPIRED`, `REVOKED`, `RELEASED`, or `COMPLETED`; `DeliveryWindow.status` is `OPEN`, `FULL`, or `CLOSED`; `PlanGrant.status` is `ACTIVE` or `EXHAUSTED`; `FeeAllocation.status` is `ACTIVE`, `SUPERSEDED`, or `VOIDED` and its `variant` is `PROVISIONAL` or `FINAL`; `ExceptionCase.status` is `OPEN`, `UNDER_REVIEW`, `RESHIP_AUTHORIZED`, `CREDIT_ISSUED`, `DENIED`, or `CLOSED`.

### 2.7. Stale-Parent Rejection on Reservation and Adjudication

Two write operations act on a parent row whose observable state may have moved under the client's feet, and both demand that the client prove what it last saw. Both use the parent's `version` (§2.4) and both reject a mismatch with HTTP 412.

**Reserving a delivery** requires a non-optional `expected_window_version` field carrying the client's last observed `version` of the target `DeliveryWindow`. If that value does not equal the window's current `version`, the reservation is rejected with `ERR_STALE_WINDOW_VERSION` (HTTP 412). The point of the check is that another writer may already have taken a slot on that window — perfectly legitimate while `available_slots` stays positive — which makes the current writer's view of `reserved_slots`, `available_slots`, and `status` obsolete.

**Adjudicating an exception case** requires a non-optional `expected_delivery_version` field carrying the client's last observed `version` of the case's `Delivery`. If that value does not equal the delivery's current `version`, the adjudication is rejected with `ERR_STALE_DELIVERY_VERSION` (HTTP 412). The delivery may in the meantime have been settled, waived, returned, or re-linked to another reship — each of which legitimately supersedes the operator's understanding of what the adjudication would do.

No other endpoint takes a version field. Requests to any other endpoint neither require nor accept `expected_window_version` or `expected_delivery_version`, and are processed with no stale-parent check.

### 2.8. Money, Cents and Rounding Discipline

All money in this system is carried as **integer cents**. There are no fractional-cent fields, no currency strings, and no floating-point totals in any response. Fee schedule inputs (`base_fee_cents`, `per_mile_cents`, `cold_pack_fee_cents`, `controlled_handling_fee_cents`, `after_hours_fee_cents`), grant pool figures (`grant_budget_cents`, `per_delivery_cap_cents`, `committed_cents`, `consumed_cents`, `remaining_cents`), every fee line, and every party's share are whole numbers of cents.

Rounding therefore appears in exactly one place in the pricing chain: converting a fee line into the member's share of it. That conversion multiplies the line by a cost-share fraction and rounds the product **half up** to a whole cent. It is applied once **per line item**, and the rounded per-line results are then summed. Rounding the fee subtotal once, after summation, is a different and incorrect answer whenever two or more lines land on a half cent, and the system must not do it.

`HealthPlan.member_cost_share_pct` is the only fractional field in the money chain: it is a number between 0.00 and 1.00 inclusive carrying exactly two decimal places, and `FeeAllocation.cost_share_pct_applied` records the fraction that was actually used on a given allocation. `DeliveryZone.distance_band_miles` is likewise a decimal — between 0.1 and 60.0 inclusive with one decimal place — but it is rounded **up to a whole mile before** it is multiplied by the per-mile rate, never after.

The two courier reliability scores are the system's only other non-integer stored values; both are held to two decimal places, rounded half up, and compared at that precision.

### 2.9. Cascade Discipline and Grant-Fund Conservation

The consistency model is immediate: by the time a response is written, every derived count, score, status, and money figure the request touched has already been brought into line. Derived quantities are recomputed from their defining membership rather than blindly incremented — `reserved_slots` on a window is a count of deliveries in a reserved custody set, `active_delivery_count` on a courier is a count of that courier's accepted assignments, and `committed_cents` and `consumed_cents` on a grant pool are sums over that pool's allocations.

Grant funds obey a conservation rule that must hold after every request. A pool's `remaining_cents` is always its `grant_budget_cents` minus its `committed_cents` minus its `consumed_cents`. Money is *committed* while a provisional bill is in force and *consumed* once a final bill is in force: `committed_cents` is the sum of `plan_grant_cents` across that pool's allocations whose `status` is `ACTIVE` and whose `variant` is `PROVISIONAL`, and `consumed_cents` is the same sum across allocations whose `status` is `ACTIVE` and whose `variant` is `FINAL`. Whenever an allocation stops being `ACTIVE` — because it was superseded by a final bill, voided by a cancellation, voided by a cold-chain breach, or voided by a fee credit — the funds it held are released from the pool in the same request. A pool moves to `EXHAUSTED` the moment `remaining_cents` reaches 0, which removes it from the subsidy selector's candidate set; a release that lifts `remaining_cents` back above 0 returns it to `ACTIVE`. Both directions bump the pool's `version`.

The same discipline governs the delivery's own money mirror: `Delivery.fee_subtotal_cents` always equals the `fee_subtotal_cents` of that delivery's `ACTIVE` fee allocation, and is 0 when the delivery has no `ACTIVE` allocation at all.

### 2.10. The Rule Evaluation Ladder

Rules are strictly ordered. The system evaluates them in the order below and returns the error belonging to the **lowest-numbered** rule whose condition is violated; no later rule runs once one has failed. Where a rung names several error identifiers, the parenthetical text says which one applies. This ordering is a contract, not an implementation detail — several rungs are deliberately placed so that a stronger fact masks a weaker one.

1. `X-User-ID` is present and non-empty — otherwise `ERR_UNAUTHENTICATED`. Checked on every request, ahead of routing, role resolution, and path existence.
2. The role that owns `X-User-ID` is among the addressed endpoint's authorised roles — otherwise `ERR_UNAUTHORIZED`. Applies to every endpoint.
3. An acting `PharmacyOperator`'s identifier equals the `pharmacy_id` of the `PharmacyOrder` behind the addressed resource — otherwise `ERR_PHARMACY_SCOPE_VIOLATION`. Guards releasing an order to ready, holding an order, reserving a delivery, cancelling a delivery, rescheduling a delivery, confirming a physical return, reading one order, and reading one delivery.
4. An acting `Patient`'s identifier equals the `patient_id` of the `PharmacyOrder` behind the addressed resource — otherwise `ERR_PATIENT_SCOPE_VIOLATION`. Guards cancelling a delivery, rescheduling a delivery, recording consent, reading one delivery, and reading one order.
5. An acting `Courier`'s identifier equals the `courier_id` of the addressed delivery or assignment — otherwise `ERR_COURIER_SCOPE_VIOLATION`. Guards accepting an offer, declining an offer, changing courier availability, pickup, departure, recording a door-step attempt, the courier-limited projection, reading one courier, and reading a courier's disclosure trail.
6. An acting `PlanAdministrator`'s identifier equals the `health_plan_id` of the addressed grant pool, or of the `PharmacyOrder` behind the addressed delivery — otherwise `ERR_PLAN_SCOPE_VIOLATION`. Guards funding a grant pool, reading one grant pool, listing grant pools, reading one fee allocation, listing fee allocations, and reading one delivery.
7. A `Courier` requesting the courier-limited projection of a delivery holds a `CourierAssignment` on that delivery whose `status` is `OFFERED`, `ACCEPTED`, or `COMPLETED`, or is that delivery's `courier_id` — otherwise `ERR_HIPAA_SCOPE_VIOLATION`. This is the minimum-necessary rule: no live or historical assignment means no disclosure at all, not even the redacted one.
8. Every identifier segment in the path resolves to a stored row of the addressed collection — otherwise the 404 belonging to that collection: `ERR_ORDER_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_COURIER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_EXCEPTION_CASE_NOT_FOUND`, `ERR_PLAN_GRANT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`, or `ERR_PATIENT_NOT_FOUND`. Existence is deliberately checked *after* scoping, so probing a real identifier belonging to another tenant yields 403 rather than leaking the difference between 404 and 200.
9. The request body parses, contains every required field, and satisfies every declared type, enum, range, and format constraint — otherwise `ERR_INVALID_REQUEST`. This rung also covers pagination bounds, two-decimal percentage checks, ISO 8601 shape, and unknown enum members.
10. Every foreign key supplied in the request body resolves to a stored row — otherwise `ERR_ORDER_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_COURIER_NOT_FOUND`, `ERR_PLAN_GRANT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, or `ERR_REFERENCE_NOT_FOUND` for a referenced health plan, pharmacy, or delivery zone that has no dedicated code of its own. Applies to funding a grant pool, registering a patient, onboarding a courier, publishing a window, order intake, reserving a delivery, rescheduling, dispatching, opening an exception case, and adjudicating.
11. The adjudicating operations user is neither the case's `opened_by_ops_user_id` nor the `revoked_by_ops_user_id` of any `CourierAssignment` on the case's delivery — otherwise `ERR_SEGREGATION_OF_DUTIES`. This needs the case row, so it sits after existence, but it is an authorisation decision and therefore ahead of every state check. A system-opened case, whose `opened_by_ops_user_id` is null, is adjudicable by any operations user who did not revoke an assignment on that delivery. Applies to adjudication regardless of which `disposition` is requested.
12. `PharmacyOrder.status` is the state the operation requires — otherwise `ERR_ORDER_NOT_READY` where `READY` is specifically required (reserving a delivery, holding an order), and `ERR_INVALID_ORDER_STATE` for the other mismatches (releasing to ready requires `INTAKE`; pickup requires `DISPATCHED`).
13. `Delivery.custody_status` is in the operation's allowed from-set — otherwise `ERR_INVALID_CUSTODY_STATE`. Guards dispatching, pickup, departure, recording an attempt, cancelling, rescheduling, confirming a return, settling, and opening an exception case, and it is what locks down the terminal values `DELIVERED`, `RETURNED`, and `CANCELLED`.
14. `Delivery.settlement_status` is `PROVISIONAL` wherever the operation moves the money dimension — otherwise `ERR_INVALID_SETTLEMENT_STATE`. Guards settling and adjudicating. This is independent of custody: a `DELIVERED` delivery already `FINALIZED` cannot be settled twice, and a `WAIVED` one cannot be credited twice.
15. `CourierAssignment.status` is `OFFERED` for accept and decline, and either `OFFERED` or `ACCEPTED` for revoke — otherwise `ERR_INVALID_ASSIGNMENT_STATE`; then, for accept only, the clock is earlier than `offer_expires_at` — otherwise `ERR_OFFER_EXPIRED`. The status mismatch is reported first, so declining an already-declined offer reports the status rather than the expired time-to-live.
16. `ExceptionCase.status` is `OPEN` to start review, `UNDER_REVIEW` to adjudicate, and one of `RESHIP_AUTHORIZED`, `CREDIT_ISSUED`, or `DENIED` to close — otherwise `ERR_INVALID_EXCEPTION_STATE`. Adjudicating straight out of `OPEN` is rejected; the review step cannot be skipped.
17. `Courier.status` is compatible with the operation — otherwise `ERR_COURIER_SUSPENDED` when the courier is `SUSPENDED` at dispatch or accept, `ERR_COURIER_UNAVAILABLE` when it is `OFFLINE` at dispatch or accept, and `ERR_INVALID_COURIER_STATE` for an illegal availability change (going `OFFLINE` while `active_delivery_count` is greater than 0, or a `Courier` trying to clear its own `SUSPENDED` status). When a courier is both suspended and unavailable, suspension is reported, because it is the stronger fact. `ON_ROUTE` is deliberately **not** rejected here: a courier already carrying a leg is a legitimate dispatch target, and rung 36 is what actually bounds its load.
18. `DeliveryWindow.status` is not `CLOSED`, and for a reservation is not `FULL` — otherwise `ERR_WINDOW_CLOSED`. Guards reserving a delivery, rescheduling, and departure. This is a status-flag check only; comparing the clock against `window_end` is a separate rule at rung 34, which deliberately loses to the safety rules in between.
19. The order's health plan has an `ACTIVE` grant pool whose `benefit_year` equals the UTC calendar year of the target window's `window_start` and whose `health_plan_id` equals the order's `health_plan_id` — otherwise `ERR_GRANT_NOT_APPLICABLE`. Grant selection is deterministic: among that plan's `ACTIVE` pools for the window's benefit year, the one with the lowest `created_at` is used. Guards reserving a delivery, rescheduling, settling, and adjudicating. A self-pay order, whose `health_plan_id` is null, needs no pool and never trips this rung.
20. `expected_window_version` equals the target window's `version` — otherwise `ERR_STALE_WINDOW_VERSION` (412) on reserving a delivery. Evaluated after every state precondition and ahead of every business rule.
21. `expected_delivery_version` equals the delivery's `version` — otherwise `ERR_STALE_DELIVERY_VERSION` (412) on adjudicating.
22. `Patient.hipaa_consent_status` is `GRANTED` — otherwise `ERR_CONSENT_NOT_GRANTED`. Guards releasing an order to ready and reserving a delivery; an order cannot advance on the state of a different aggregate without this being true.
23. `Pharmacy.controlled_license_tier` covers the order's `controlled_schedule`, and `Pharmacy.cold_chain_certified` is true whenever `cold_chain_required` is true — otherwise `ERR_CONTROLLED_NOT_LICENSED` on releasing an order to ready. The coverage ladder is: `NONE` covers only `NONE`; `CIII_V` covers `NONE` and `CIII`; `CII_V` covers `NONE`, `CIII`, and `CII`.
24. `DeliveryZone.controlled_delivery_allowed` is true whenever the delivery's `handling_class` is `CONTROLLED` or `COLD_CHAIN_CONTROLLED` — otherwise `ERR_CONTROLLED_ZONE_PROHIBITED` on reserving a delivery or rescheduling.
25. `DeliveryZone.cold_chain_supported` is true whenever the delivery's `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED` — otherwise `ERR_COLD_CHAIN_UNSUPPORTED_ZONE` on reserving a delivery or rescheduling.
26. An explicitly named courier is `cold_chain_equipped` when the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`, is `controlled_certified` when it is `CONTROLLED` or `COLD_CHAIN_CONTROLLED`, serves the window zone's `zone_code`, and has a `mode` equal to the window's `courier_mode` — otherwise `ERR_COURIER_NOT_COLD_CERTIFIED`, `ERR_COURIER_NOT_CONTROLLED_CERTIFIED`, `ERR_COURIER_ZONE_NOT_SERVED`, or `ERR_COURIER_MODE_MISMATCH` respectively, on dispatch. Only reachable on the explicit-courier override; the automatic selector silently filters uncertified couriers instead. Placed deliberately ahead of rung 34: an uncertified handoff is a patient-safety fact, a late window is only a scheduling fact.
27. `cold_chain_seal_id` is present at pickup when the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED` — otherwise `ERR_COLD_SEAL_REQUIRED`. For `STANDARD` and `CONTROLLED` classes the field is simply ignored.
28. When the delivery's `signature_required` is true and the recorded outcome is `DELIVERED`, `signature_captured` is true and `recipient_relationship` is not `UNATTENDED` — otherwise `ERR_SIGNATURE_REQUIRED` for the missing signature, or `ERR_UNATTENDED_NOT_PERMITTED` when a signature is claimed but the drop is recorded as `UNATTENDED`.
29. When the recorded outcome is `DELIVERED`, `id_verification_method` ranks at or above the delivery's `required_id_verification` on the strictly increasing ladder `NONE`, `DOB_MATCH`, `PHOTO_ID`, `GOVT_ID_SCAN` — otherwise `ERR_ID_VERIFICATION_INSUFFICIENT`. A courier who cannot clear the bar must record `ID_MISMATCH` instead, which is an ordinary ladder failure rather than an error.
30. `Patient.zone_code` names an existing delivery zone and the target window's `zone_id` is that zone — otherwise `ERR_ZONE_NOT_SERVICED` when the patient's `zone_code` matches no zone row, and `ERR_ZONE_MISMATCH` when the window belongs to a different zone. Guards reserving a delivery, rescheduling, and adjudicating, where a reship window must sit in the original window's zone.
31. A replacement or reship window's `courier_mode` equals the `courier_mode` of the window the delivery currently holds — otherwise `ERR_WINDOW_MODE_MISMATCH` on rescheduling and adjudicating. On-demand and scheduled capacity pools are not interchangeable. Not applicable to the initial reservation, where the chosen window itself establishes the mode.
32. The order has no delivery other than the one addressed by the request whose `custody_status` is something other than `CANCELLED` or `RETURNED` — otherwise `ERR_DUPLICATE_ACTIVE_DELIVERY`. Guards reserving a delivery and adjudicating. At reservation time rung 12 normally speaks first, so the reachable trigger is a second reship adjudication: the case's own delivery is exempt, but a reship delivery already spawned for the same order is not, which blocks a double reship ahead of the weaker rung 41.
33. `PharmacyOrder.hold_count` is below 2 — otherwise `ERR_MAX_HOLDS_EXCEEDED` on holding an order.
34. The clock is earlier than the target window's `window_end`, and for a *new* reservation on a `SCHEDULED` window the clock is at or before `window_start` minus two hours — otherwise `ERR_WINDOW_ELAPSED`. Guards reserving a delivery, rescheduling, dispatching, and departure. `ON_DEMAND` windows carry no lead-time requirement and may be reserved right up to `window_end`.
35. `window_start` is strictly earlier than `window_end` — otherwise `ERR_WINDOW_INTERVAL_INVALID` — and the candidate interval does not overlap a non-`CLOSED` window of the same `zone_id` and `courier_mode` under half-open comparison — otherwise `ERR_WINDOW_OVERLAP`. Applies to publishing a window.
36. The courier holds no `ACCEPTED` assignment whose buffered closed interval touches the target window — otherwise `ERR_COURIER_OVERLAP_CONFLICT` on dispatch and accept.
37. The clock is at or after `last_attempt_at` plus the cooldown for the current rung — otherwise `ERR_REATTEMPT_COOLDOWN_ACTIVE` on departure. One hour after the first failure, three hours after the second; exactly at the boundary passes.
38. The target window's `available_slots` is at least 1 — otherwise `ERR_WINDOW_FULL`. Guards reserving a delivery, rescheduling, and adjudicating. This is the aggregate check: each individual reservation is legal but the collective would exceed `capacity_slots`.
39. The selector's candidate pool is non-empty when a dispatch arrives without an explicit `courier_id` — otherwise `ERR_NO_ELIGIBLE_COURIER`, with nothing mutated.
40. For a `MEDICAID` plan, the grant-eligible amount equals `patient_gross_share_cents` in full — otherwise `ERR_GRANT_COVERAGE_INSUFFICIENT`. Guards reserving a delivery, rescheduling, settling, and adjudicating. Being last in the ladder, this rule deliberately loses to every state check: an order that is not `READY` reports `ERR_ORDER_NOT_READY` even when the grant is also short.
41. No exception case on the delivery is `OPEN` or `UNDER_REVIEW` at settlement — otherwise `ERR_EXCEPTION_PENDING` — and a delivery already linked to a reship cannot be adjudicated to `RESHIP` again, nor may a `RESHIP` disposition arrive without a `reship_window_id` — otherwise `ERR_OVERRIDE_ADJUDICATION_CONFLICT`.

### 2.11. HIPAA Minimum-Necessary Disclosure to Couriers

Couriers are third parties. They never receive a delivery's full record; they receive a **courier-limited projection**, and every release of that projection is logged as a `CourierDataDisclosure` row that cannot afterwards be edited.

The projection contains exactly thirteen values: `delivery_id`, `order_id`, `patient_masked_name`, `patient_phone_last4`, `address_line`, `window_start`, `window_end`, `handling_class`, `signature_required`, `required_id_verification`, `rx_line_count`, `redacted_field_count`, and `disclosure_id`, the last being the `id` of the disclosure row just appended. `patient_masked_name` is the patient's `masked_name` and `patient_phone_last4` is the patient's `phone_last4` — the only phone data ever released to a courier.

`masked_name` is derived from `full_name` by splitting it on whitespace and, in each resulting token, keeping the first character and replacing every remaining character with an asterisk; "Dana Reyes" becomes "D\*\*\* R\*\*\*\*".

Six fields drawn from the delivery, the order, and the patient are withheld from the projection: `full_name`, `date_of_birth`, `total_rx_value_cents`, `controlled_schedule`, `health_plan_id`, and the delivery's `fee_subtotal_cents` — no fee figure of any kind reaches a courier. `redacted_field_count` on the disclosure row and in the projection is the count of those withheld fields, so it is 6. The complementary `fields_disclosed` on the disclosure row is the sorted list of field names that *were* released.

Each disclosure row also records `delivery_id`, `courier_id` (null when a `NetworkOps` operator previewed the courier view rather than a courier reading it), `disclosed_at` from the clock, a `purpose` that is either `ROUTING` or `DELIVERY_EXECUTION` and defaults to `DELIVERY_EXECUTION`, and a `minimization_profile`, whose only value is `COURIER_LIMITED`.

Two audit reads expose that trail from opposite ends: one lists every projection a given courier has been shown, the other lists every courier who has been shown a given delivery. Both are paginated per §2.3.

### 2.12. Path Identifier Resolution and Reference Integrity

When a path carries an identifier, that identifier is resolved left to right and the first segment that names no stored row terminates the request with the 404 belonging to *that* collection — a disclosure trail requested under an unknown delivery reports `ERR_DELIVERY_NOT_FOUND` before the system considers anything else, and a courier-view request under an unknown delivery does the same. Resolution happens only after the scoping rules of §2.1 have passed, so a caller cannot use 404-versus-403 to discover whether some other tenant's identifier exists.

Foreign keys travelling in a request body are resolved on the same principle but with their own codes. A `patient_id` that names no patient reports `ERR_PATIENT_NOT_FOUND`; an `order_id` with no order reports `ERR_ORDER_NOT_FOUND`; a `window_id` or `reship_window_id` with no window reports `ERR_WINDOW_NOT_FOUND`; a `courier_id` with no courier reports `ERR_COURIER_NOT_FOUND`; a `plan_grant_id` with no pool reports `ERR_PLAN_GRANT_NOT_FOUND`. A referenced health plan, pharmacy, or delivery zone has no dedicated code and reports `ERR_REFERENCE_NOT_FOUND` — this is what a bad `health_plan_id`, `pharmacy_id`, or `zone_code` yields, the latter being resolved by natural key rather than by identifier.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Network: Payers, Grants, Sites, Zones and Windows

Before a single bag moves, `NetworkOps` populates the reference layer. A payer is registered as a **health plan** with a `name` of 1 to 120 characters, a `payer_type` that is one of `COMMERCIAL`, `MEDICAID`, or `MEDICARE_ADVANTAGE`, and a `member_cost_share_pct` — the fraction of each delivery-fee line item the member bears before any subsidy, given to exactly two decimals between 0.00 and 1.00 inclusive. The `MEDICAID` value is not merely descriptive; it triggers the zero-member-cost mandate described in §3.3.

A payer or an operator then funds a **grant pool** against that plan by supplying `health_plan_id`, a `benefit_year` between 2026 and 2030 inclusive, a `grant_budget_cents` greater than zero, and a `per_delivery_cap_cents` of zero or more, which is the most this pool will ever commit to a single delivery. A freshly funded pool starts with `committed_cents` and `consumed_cents` at 0, `remaining_cents` equal to `grant_budget_cents`, and `status` `ACTIVE`. The `benefit_year` is matched against the UTC calendar year of a delivery window's `window_start`, not against the clock at the time of the request, so a December order for a January window draws on next year's money.

A **dispensing site** is registered with a `name` of 1 to 120 characters, a `state_code` of exactly two uppercase letters, a `cold_chain_certified` flag defaulting to false, a `controlled_license_tier` of `NONE`, `CIII_V`, or `CII_V` defaulting to `NONE`, and a `return_window_minutes` defaulting to 240 and constrained to between 60 and 1440 inclusive — the grace period the site gets between a bag entering `RETURN_PENDING` and the site confirming it back in hand.

A **delivery zone** carries the fee schedule for its territory. Its `zone_code` is a natural key of 2 to 12 characters that must be unique across all zones, and its `distance_band_miles` is the billable distance band, one decimal place, between 0.1 and 60.0 inclusive. Five money fields follow, all zero or greater: `base_fee_cents` for the flat per-delivery line, `per_mile_cents` for the mileage line, `cold_pack_fee_cents` charged per cold pack consumed, `controlled_handling_fee_cents` applied once when the bag carries a controlled schedule, and `after_hours_fee_cents` applied once when the promised window falls after hours. Two booleans, `cold_chain_supported` and `controlled_delivery_allowed`, both defaulting to true, say whether refrigerated product and scheduled drugs may be routed into the zone at all — some municipalities forbid courier delivery of controlled substances outright.

A **recipient** is registered with `full_name` (1 to 120 characters), `date_of_birth` as an ISO calendar date in `YYYY-MM-DD` form, `phone_last4` as exactly four digits, an `address_line` of 1 to 200 characters, a `zone_code` of 2 to 12 characters that must name an existing zone, and an optional `hipaa_consent_status` of `GRANTED` or `REVOKED` that defaults to `GRANTED`. The system derives `masked_name` at registration for the courier-facing projection. Either the patient themselves or a pharmacy operator may afterwards submit a fresh `hipaa_consent_status`, which is the switch that authorises third-party courier disclosure; flipping it to `REVOKED` immediately blocks release of that patient's orders and reservation of new deliveries with `ERR_CONSENT_NOT_GRANTED`, and each such change bumps the patient's `version`.

**Capacity windows** are published one at a time against a `zone_id` and a `courier_mode` of `ON_DEMAND` or `SCHEDULED`, with a `window_start`, a `window_end`, and a `capacity_slots` of at least 1. Publication requires `window_start` strictly earlier than `window_end`, or the request fails with `ERR_WINDOW_INTERVAL_INVALID`. It then requires temporal uniqueness within the zone and mode: for every existing window in the same `zone_id` with the same `courier_mode` whose `status` is not `CLOSED`, the candidate conflicts when the candidate's `window_start` is strictly earlier than that window's `window_end` **and** that window's `window_start` is strictly earlier than the candidate's `window_end`. Any conflict is `ERR_WINDOW_OVERLAP`. Because both comparisons are strict, a candidate starting exactly when an existing window ends misses on the first comparison and is allowed — adjacency is not a conflict — and the same interval published under the other `courier_mode` is a different capacity pool and is likewise allowed. A new window starts with `reserved_slots` at 0, `available_slots` equal to `capacity_slots`, `status` `OPEN`, and `is_after_hours` derived from `window_start` per §2.5.

Occupancy of a window is defined by membership, not by a counter. `reserved_slots` is the number of deliveries pointing at that window whose `custody_status` is `QUEUED`, `ASSIGNED`, `PICKED_UP`, `OUT_FOR_DELIVERY`, or `ATTEMPT_FAILED`; `available_slots` is `capacity_slots` minus `reserved_slots`, never allowed below zero. The window is `OPEN` while `reserved_slots` is below `capacity_slots` and the clock is still earlier than `window_end`, becomes `FULL` exactly when `reserved_slots` equals `capacity_slots`, and becomes `CLOSED` — permanently — once a routing sweep observes the clock at or after `window_end`. Reaching capacity moves `OPEN` to `FULL`; any slot release while the clock is still earlier than `window_end` moves `FULL` back to `OPEN`. Both directions bump the window's `version`. `DELIVERED`, `RETURN_PENDING`, `RETURNED`, and `CANCELLED` all release the slot; `ATTEMPT_FAILED` does not, because the bag is still out against that window.

Couriers are onboarded with a `display_name` of 1 to 80 characters shown on the patient tracker, a `mode` of `ON_DEMAND` or `SCHEDULED`, a non-empty `served_zone_codes` array of zone codes each 2 to 12 characters long, and optional `cold_chain_equipped` and `controlled_certified` booleans that both default to false. A new courier starts `OFFLINE` with `active_delivery_count` at 0, `attempt_total_count` and `delivered_count` at 0, and both `rolling_reliability_score` and `lifetime_reliability_score` at 100.00.

### 3.2. Intake at the Dispensing Counter

A `PharmacyOperator` takes a filled bundle into the system by declaring the `pharmacy_id` of the dispensing site, the `patient_id` of the recipient, an optional `health_plan_id` naming the payer pinned at intake (omitted or null for a self-pay bag), an `rx_line_count` of at least 1 for the number of prescription lines in the bag, an optional `cold_chain_required` flag defaulting to false, an optional `controlled_schedule` of `NONE`, `CIII`, or `CII` defaulting to `NONE`, and a `total_rx_value_cents` of zero or more giving the retail value of the bag. The order lands at `status` `INTAKE` with `hold_count` at 0.

From those three handling inputs the system derives the proof requirements that will follow the bag to the door. Writing *cold* for "the bag needs a cold pack and a sealed handoff" and *controlled* for "the `controlled_schedule` is anything other than `NONE`": `signature_required` is true when the bag is cold, or controlled, or its `total_rx_value_cents` is at least 25000 cents — that is, at least 250 dollars, with a bag valued at exactly 250 dollars already requiring a signature. `required_id_verification` is selected by a strictly ordered cascade: a `CII` schedule demands `GOVT_ID_SCAN`; failing that, a `CIII` schedule demands `PHOTO_ID`; failing that, a `total_rx_value_cents` of at least 25000 demands `PHOTO_ID`; and everything else, cold bags included, settles at `DOB_MATCH`, which is checked against the patient's `date_of_birth` at the door. These two derived fields are recomputed each time the order is released for scheduling, so they always reflect the flags in force at that moment.

Releasing an order advances it from `INTAKE` to `READY` and is the compliance gate of the whole workflow. It requires the order to be at `INTAKE`, the acting operator to own the order's `pharmacy_id`, the recipient's `hipaa_consent_status` to be `GRANTED`, and the site's credentials to cover the bag: `controlled_license_tier` `NONE` covers only a `NONE` schedule, `CIII_V` covers `NONE` and `CIII`, and `CII_V` covers `NONE`, `CIII`, and `CII`, while a cold bag additionally requires `cold_chain_certified` to be true. A credential shortfall is `ERR_CONTROLLED_NOT_LICENSED`; a revoked consent is `ERR_CONSENT_NOT_GRANTED`; attempting the release on an order that is not at `INTAKE` is `ERR_INVALID_ORDER_STATE`. On success the two derived proof fields are recomputed and the order's `version` increments.

A release is reversible. Pulling a `READY` order back to `INTAKE` for re-verification requires the order to be `READY` — otherwise `ERR_ORDER_NOT_READY` — and requires `hold_count` to be below 2; the third attempt is rejected with `ERR_MAX_HOLDS_EXCEEDED`. Each successful hold increments `hold_count` and the order's `version`, and may carry an optional free-text `notes`. Because reserving a delivery immediately drives the order to `DISPATCHED`, a `READY` order never has a live delivery behind it, so the hold path never has to unwind a reservation. The `INTAKE` to `READY` to `INTAKE` revision loop is thus bounded at two round trips.

The order's own `status` closes the loop with the delivery lifecycle in three further ways: reserving a delivery drives `READY` to `DISPATCHED`; settling a delivery whose custody reached `DELIVERED` drives `DISPATCHED` to `CLOSED`; and a confirmed physical return drives `DISPATCHED` to `RETURNED_TO_STOCK`. `CLOSED` and `RETURNED_TO_STOCK` are terminal and are the divergent outcomes of the same `DISPATCHED` state — one means the bag reached the patient, the other means it came back. Cancelling the order's only live delivery drives `DISPATCHED` back to `READY`, closing the compensating cycle and making the order schedulable again. Every one of these transitions bumps the order's `version`.

### 3.3. Reserving a Window and Building the Provisional Bill

A `PharmacyOperator` reserves capacity for a `READY` order by naming the `order_id`, the `window_id` of the promised interval, and the `expected_window_version` proving which view of that window's occupancy the client is acting on (§2.7). The order must be `READY`, or the request is `ERR_ORDER_NOT_READY`; the recipient's consent must still be `GRANTED`; the window must not be `CLOSED` or `FULL` by status flag, or the request is `ERR_WINDOW_CLOSED`; the window's `zone_id` must be the zone named by the recipient's `zone_code`, or the request is `ERR_ZONE_MISMATCH`, while a `zone_code` matching no zone row at all is `ERR_ZONE_NOT_SERVICED`. Zone policy then applies to the bag: a controlled bag into a zone whose `controlled_delivery_allowed` is false is `ERR_CONTROLLED_ZONE_PROHIBITED`, and a cold bag into a zone whose `cold_chain_supported` is false is `ERR_COLD_CHAIN_UNSUPPORTED_ZONE`. Timing applies next: the clock must be earlier than `window_end`, and for a `SCHEDULED` window the reservation must arrive no later than two hours before `window_start`; either failure is `ERR_WINDOW_ELAPSED`. An `ON_DEMAND` window has no lead-time requirement. Finally the aggregate capacity check runs, and a window whose `available_slots` has fallen to zero is `ERR_WINDOW_FULL`.

On success a `Delivery` row appears with `custody_status` `QUEUED` and `settlement_status` `PROVISIONAL`, carrying `order_id` and `window_id`, a null `courier_id`, a null `reship_of_delivery_id`, an `attempt_count` of 0, a null `last_attempt_at`, an empty `excluded_courier_ids`, a null `cold_chain_seal_id`, a null `picked_up_at`, a null `delivered_at`, and a null `return_due_at`. Three values are snapshotted off the order at this instant and never re-derived afterwards: `handling_class`, `signature_required`, and `required_id_verification`. The `handling_class` is `COLD_CHAIN_CONTROLLED` when the bag is both cold and controlled, `COLD_CHAIN` when it is only cold, `CONTROLLED` when it is only controlled, and `STANDARD` otherwise. The window's `reserved_slots` rises by one and it flips to `FULL` if that reaches `capacity_slots`; the order moves to `DISPATCHED`; and the bill is built. Window, order, and grant pool each bump their own `version`.

**The six-line bill.** Pricing produces an ordered vector of six line items, never a pre-summed total, because every downstream money rule consumes the vector rather than the sum. Zeros are retained in position. Let *billable attempts* mean the number of door-step runs the bill is charging for; on a provisional bill it is pinned to 1, since no run has happened yet. The lines are, in order:

1. `base_line_cents` is the zone's `base_fee_cents`.
2. `mileage_line_cents` is the zone's `per_mile_cents` multiplied by the zone's `distance_band_miles` rounded up to the next whole mile. The rounding up happens *before* the multiplication, never after.
3. `cold_pack_line_cents` is the zone's `cold_pack_fee_cents` multiplied by the billable attempts when the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`, and 0 otherwise — each door-step run needs a fresh gel-pack re-ice.
4. `controlled_line_cents` is the zone's `controlled_handling_fee_cents` when the `handling_class` is `CONTROLLED` or `COLD_CHAIN_CONTROLLED`, and 0 otherwise. It is charged once regardless of how many runs were made.
5. `after_hours_line_cents` is the zone's `after_hours_fee_cents` when the window's `window_start` falls at or after 20:00 UTC or before 06:00 UTC, and 0 otherwise. It, too, is charged once.
6. `reattempt_line_cents` is 400 cents for each billable attempt beyond the first, counting no fewer than zero such units and no more than two — so a bill charging one run has no surcharge, two runs carry 400 cents, three runs carry 800 cents, and the cap holds the line at 800 cents however many runs a future policy might allow.

`fee_subtotal_cents` on the allocation is the sum of those six lines.

**The member's gross share.** Each of the six lines is separately adjudicated as a benefit item, so the member's share is computed line by line: multiply each line by the applicable cost-share fraction, round each product half up to a whole cent, and only then add the six rounded results together to obtain `patient_gross_share_cents`. The fraction used is the payer's `member_cost_share_pct`, or 1.00 for a self-pay order with no `health_plan_id`, and it is recorded on the allocation as `cost_share_pct_applied`. Multiplying the subtotal by the fraction and rounding once is a different figure whenever two or more lines land on a half cent, and it is the wrong answer.

**The payer-mix waterfall.** The subtotal is then split three ways in a strictly pinned order. First, the grant-eligible amount is the smallest of three quantities: the member's gross share, the selected pool's `per_delivery_cap_cents`, and the pool's `remaining_cents`. Second — and only for a `MEDICAID` payer — if that eligible amount is less than the gross share, the request is rejected outright with `ERR_GRANT_COVERAGE_INSUFFICIENT`: a Medicaid member may not be billed any residue, so a pool that can only partly fund the share cannot be used at all. Third, `plan_grant_cents` is set to the eligible amount and `plan_grant_id` records the pool it came from; a self-pay order selects no pool, leaves `plan_grant_id` null, and carries `plan_grant_cents` of 0. Fourth, the member's pre-absorption net is the gross share minus `plan_grant_cents`. Fifth, the pharmacy's goodwill tier is chosen **from that pre-absorption net and never re-derived from anything later**: a net of 1000 cents or more selects `absorption_tier_cents` of 500, a net of 500 cents or more but under 1000 selects 200, any net of at least 1 cent but under 500 selects 50, and a net of zero selects 0. `pharmacy_absorption_cents` is the smaller of the selected tier and the pre-absorption net, so absorption can never push the patient below zero. Sixth, `patient_payable_cents` is the pre-absorption net minus `pharmacy_absorption_cents`, and `pharmacy_payable_cents` is `fee_subtotal_cents` minus `plan_grant_cents` minus `patient_payable_cents` — which means the pharmacy line carries both the absorbed goodwill slice and the entire non-member portion of the bill. The three payer figures always add back up to `fee_subtotal_cents` exactly; that identity is an invariant of every allocation the system writes.

Choosing the pool is deterministic and happens before any of the arithmetic: among the order's plan's `ACTIVE` pools whose `benefit_year` equals the UTC calendar year of the target window's `window_start`, the one with the lowest `created_at` wins. If the plan has none, the reservation fails with `ERR_GRANT_NOT_APPLICABLE`. The resulting `FeeAllocation` is written with `delivery_id`, `variant` `PROVISIONAL`, and `status` `ACTIVE`, its `plan_grant_cents` is added to the pool's `committed_cents`, the pool's `remaining_cents` and `status` are recomputed, and the delivery's `fee_subtotal_cents` mirrors the allocation's. Allocations are never edited: a superseded or voided allocation stays readable forever, which is why the allocation list exposes `variant` and `status` filters over the full history.

### 3.4. Routing: Offers, the Selector and Operator Overrides

A `QUEUED` delivery reaches a courier through an offer, which only `NetworkOps` may create. Dispatch takes an optional `courier_id`; supplying it is an operator override, omitting it invokes the automatic selector. Either way the delivery's custody must be `QUEUED` — anything else is `ERR_INVALID_CUSTODY_STATE` — and the clock must still be earlier than the window's `window_end`, or the dispatch is `ERR_WINDOW_ELAPSED`.

**The selector.** A courier is a candidate only when every one of the following holds: its `status` is `AVAILABLE` or `ON_ROUTE`; its `mode` equals the window's `courier_mode`; the window zone's `zone_code` appears in its `served_zone_codes`; its identifier is not in the delivery's `excluded_courier_ids`; it is `cold_chain_equipped` if the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`; it is `controlled_certified` if the `handling_class` is `CONTROLLED` or `COLD_CHAIN_CONTROLLED`; and it holds no `ACCEPTED` assignment whose buffered committed interval touches this window. Candidates are then ordered by `rolling_reliability_score` descending, ties broken by `active_delivery_count` ascending, and any remaining ties broken by `created_at` ascending — never by identifier. The first row after that ordering is the courier offered the job. When the candidate pool is empty, no assignment is created, nothing at all is mutated, the delivery stays `QUEUED`, and the request fails with `ERR_NO_ELIGIBLE_COURIER`.

**The buffered-interval rule.** A courier's committed time is not the bare window. For every `ACCEPTED` assignment the courier holds, take the window of that assignment's delivery and pad it by a quarter of an hour on each end — from `window_start` minus 15 minutes to `window_end` plus 15 minutes — treating the padded interval as *closed* at both ends. A candidate window conflicts when the candidate's `window_start` is at or before the padded upper bound **and** the padded lower bound is at or before the candidate's `window_end`. Because the comparisons are non-strict, sharing an endpoint with the padded interval *is* a conflict. Two windows that sit back to back are perfectly legal for a zone (§3.1 uses strict comparison on half-open intervals) yet illegal for one courier, and that asymmetry is intentional: the courier needs turnaround time the zone does not. When this conflict is detected during selector filtering the courier is silently dropped from the pool with no error of its own; when it is detected at accept time it is reported as `ERR_COURIER_OVERLAP_CONFLICT`.

**The operator override.** When a dispatch names an explicit `courier_id`, ranking is bypassed but safety is not. The named courier must be `cold_chain_equipped` for a cold bag (`ERR_COURIER_NOT_COLD_CERTIFIED`), `controlled_certified` for a controlled bag (`ERR_COURIER_NOT_CONTROLLED_CERTIFIED`), serve the window zone's `zone_code` (`ERR_COURIER_ZONE_NOT_SERVED`), and have a `mode` matching the window's `courier_mode` (`ERR_COURIER_MODE_MISMATCH`); it must not be `SUSPENDED` (`ERR_COURIER_SUSPENDED`) or `OFFLINE` (`ERR_COURIER_UNAVAILABLE`); and the buffered-interval rule still applies. These four certification checks are unreachable through the selector, which filters rather than complains.

Either path writes a `CourierAssignment` carrying `delivery_id`, the `courier_id` it was routed to, a `mode` copied from the courier at offer time, `status` `OFFERED`, `offered_at` stamped from the clock, an `offer_expires_at` ten minutes later, a null `responded_at`, a null `revoked_by_ops_user_id`, and a `rank_score` holding the selected courier's `rolling_reliability_score` at selection time — or 0.00 when the offer came from an operator override. The delivery stays `QUEUED`; an offer is not custody.

**Responding to an offer.** A `Courier` accepting an offer must be the assignment's `courier_id`, the assignment must be `OFFERED` (`ERR_INVALID_ASSIGNMENT_STATE`), the clock must still be earlier than `offer_expires_at` (`ERR_OFFER_EXPIRED`), the courier's own `status` must be `AVAILABLE` or `ON_ROUTE`, and the delivery must still be `QUEUED`. Acceptance sets the assignment to `ACCEPTED` with `responded_at` from the clock, advances the delivery `QUEUED → ASSIGNED` and writes its `courier_id`, raises the courier's `active_delivery_count` by one, and moves the courier `AVAILABLE → ON_ROUTE`. A courier already `ON_ROUTE` may accept a further leg whose buffered interval does not touch an existing one; that acceptance only raises `active_delivery_count` and leaves the status at `ON_ROUTE`. Temporal non-overlap, not the status flag, is what bounds a courier's concurrent load.

Declining requires the same ownership and the same `OFFERED` status. It sets the assignment to `DECLINED` with `responded_at` from the clock, may carry an optional `notes`, appends the courier to the delivery's `excluded_courier_ids` so the selector will never route this delivery to them again, and leaves custody at `QUEUED` — the delivery is immediately re-offerable to someone else.

Ops may pull an offer or an already-accepted leg back. Revocation requires the assignment to be `OFFERED` or `ACCEPTED`, and for an accepted leg requires the delivery's custody to still be `QUEUED` or `ASSIGNED`. It sets the assignment to `REVOKED`, stamps `revoked_by_ops_user_id` with the acting `X-User-ID`, appends the courier to `excluded_courier_ids`, and — when custody was `ASSIGNED` — walks it back `ASSIGNED → QUEUED` and nulls the delivery's `courier_id`. The courier's `active_delivery_count` drops by one and the courier returns `ON_ROUTE → AVAILABLE` once that count reaches 0. The re-entry into `QUEUED` closes the routing-override cycle and seeds the exclusion set, and the operator who performed it has just disqualified themselves from adjudicating any exception on that delivery (§3.8). An optional `notes` may accompany the revocation.

**The routing sweep.** A single ops capability performs three passes in order and reports what it did. First, every assignment still `OFFERED` whose `offer_expires_at` the clock has reached or passed moves `OFFERED → EXPIRED`, appending its courier to that delivery's `excluded_courier_ids`. Second, every window whose `window_end` the clock has reached or passed and whose `status` is not already `CLOSED` moves to `CLOSED`, from either `OPEN` or `FULL`; after that no delivery may reserve against it or depart against it. This sweep is the *only* thing that closes a window. Third, every `QUEUED` delivery with no `OFFERED` assignment is taken in `created_at` ascending order, run through the selector, and offered where the pool is non-empty; deliveries whose pool is empty are skipped silently rather than erroring. The response reports `expired_offer_count`, `closed_window_count`, `offers_created_count`, and `offered_delivery_ids`. Every row the sweep touches bumps its own `version`.

### 3.5. Custody: Counter Handoff, Departure and the Door-Step Run

Custody begins at the counter. Pickup requires the delivery to be `ASSIGNED`, the acting courier to be its `courier_id`, and the order behind it to be `DISPATCHED` — an order in any other state is `ERR_INVALID_ORDER_STATE`. When the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`, the request must carry a `cold_chain_seal_id`; its absence is `ERR_COLD_SEAL_REQUIRED`. For `STANDARD` and `CONTROLLED` bags the field is simply ignored. On success the delivery advances `ASSIGNED → PICKED_UP`, stores the supplied `cold_chain_seal_id`, and stamps `picked_up_at` from the clock — the instant from which the cold-chain excursion budget runs.

Departure advances `PICKED_UP → OUT_FOR_DELIVERY`, or, on a re-attempt leg, `ATTEMPT_FAILED → OUT_FOR_DELIVERY`. Either way the acting courier must be the delivery's `courier_id`, the window's `status` must not be `CLOSED`, and the clock must still be earlier than the window's `window_end`; a closed window is `ERR_WINDOW_CLOSED` and an elapsed one `ERR_WINDOW_ELAPSED`. The re-attempt leg additionally enforces the ladder gates of §3.6.

**The door-step run.** A courier records the outcome of one run by supplying a `requested_outcome` of `DELIVERED`, `NO_ANSWER`, `REFUSED`, `ADDRESS_INVALID`, or `ID_MISMATCH`, an optional `id_verification_method` of `NONE`, `DOB_MATCH`, `PHOTO_ID`, or `GOVT_ID_SCAN` (treated as `NONE` when omitted), an optional `signature_captured` boolean defaulting to false, an optional `recipient_relationship` of `SELF`, `CAREGIVER`, or `UNATTENDED` defaulting to `SELF`, and an optional `pod_photo_ref` holding an opaque reference to the proof-of-delivery photograph. The delivery must be `OUT_FOR_DELIVERY` and the acting courier must be its `courier_id`. The resulting `DeliveryAttempt` row is immutable: it records `delivery_id`, a `courier_id` copied from the delivery, an `attempt_no` equal to the delivery's `attempt_count` after this run is counted (so the first run is 1), an `attempted_at` stamped from the clock, both the `requested_outcome` as reported and the `outcome` the system actually records, the identity and signature fields as submitted, `elapsed_since_pickup_minutes` as the whole number of minutes between `picked_up_at` and `attempted_at`, and a `reliability_credit`.

**The cold-excursion override.** Before anything else is decided, the system computes `elapsed_since_pickup_minutes`. If the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED` **and** that elapsed figure is 120 minutes or more, the reported `requested_outcome` is discarded and the recorded `outcome` becomes `COLD_BREACH`. Two hours out of the box means the product is unsafe no matter what happened at the door, and no proof of delivery can override that. This is the only way `COLD_BREACH` ever appears as an `outcome`; a courier cannot report it directly.

**Recording a delivery.** For the recorded `outcome` to be `DELIVERED`, two proof gates must clear. If the delivery's `signature_required` is true, `signature_captured` must be true — a missing signature is `ERR_SIGNATURE_REQUIRED` — and `recipient_relationship` must not be `UNATTENDED`, since a claimed signature on an unattended drop is `ERR_UNATTENDED_NOT_PERMITTED`. Then the submitted `id_verification_method` must rank at or above the delivery's `required_id_verification` on the strictly increasing ladder `NONE`, `DOB_MATCH`, `PHOTO_ID`, `GOVT_ID_SCAN`; ranking below it is `ERR_ID_VERIFICATION_INSUFFICIENT`. A courier who simply cannot meet the bar at the door is expected to record `ID_MISMATCH`, which is a normal ladder failure and not an error at all.

A recorded `DELIVERED` outcome carries a `reliability_credit` of 1.0 and cascades widely: the delivery advances `OUT_FOR_DELIVERY → DELIVERED`, its `attempt_count` rises by one, `last_attempt_at` and `delivered_at` are both stamped from the clock; the courier's `ACCEPTED` assignment moves `ACCEPTED → COMPLETED`; the courier's `active_delivery_count` drops by one and the courier returns `ON_ROUTE → AVAILABLE` once it reaches 0; the courier's `attempt_total_count`, `delivered_count`, `rolling_reliability_score`, and `lifetime_reliability_score` are all recomputed; and the window's `reserved_slots` drops by one, flipping it `FULL → OPEN` if it was `FULL` and the clock is still earlier than `window_end`. The delivery's `settlement_status` does **not** move — the bill is still `PROVISIONAL` and stays that way until settlement.

### 3.6. The Re-Attempt Ladder, Return to Stock, and Changing Plans

A bag gets at most three door-step runs. Which custody state a recorded run lands in follows from one comparison: let *n* be the delivery's `attempt_count` after this run is counted. A forced `COLD_BREACH` always routes to `RETURN_PENDING`. A recorded `DELIVERED` routes to `DELIVERED`. A failure outcome — `NO_ANSWER`, `REFUSED`, `ADDRESS_INVALID`, or `ID_MISMATCH` — routes to `ATTEMPT_FAILED` while *n* is still below 3, and to `RETURN_PENDING` exactly when *n* reaches 3. Every failure outcome carries a `reliability_credit` of 0.5; a `COLD_BREACH` carries 0.0.

A run that lands at `ATTEMPT_FAILED` raises `attempt_count`, stamps `last_attempt_at` from the clock, recomputes both courier reliability scores and may cascade a suspension (§3.7), and deliberately **keeps the window slot reserved**, because the bag is still out against that window. The courier then re-departs, advancing `ATTEMPT_FAILED → OUT_FOR_DELIVERY`, but only after a cooldown that lengthens with each rung: one hour must pass after the first failure and three hours after the second, measured from `last_attempt_at` on the delivery. Arriving before that is `ERR_REATTEMPT_COOLDOWN_ACTIVE`; arriving at exactly the boundary instant is allowed. There is no separate exhaustion error on the re-departure path: because the third failure routes custody to `RETURN_PENDING` rather than back to `ATTEMPT_FAILED`, a fourth departure is already impossible and is rejected by the custody-state rule with `ERR_INVALID_CUSTODY_STATE`.

**Ladder exhaustion.** The third failure moves the delivery `OUT_FOR_DELIVERY → RETURN_PENDING`, pins `attempt_count` at 3, and sets `return_due_at` to the clock plus the dispensing site's `return_window_minutes`. It also opens an exception case with `status` `OPEN` and a null `opened_by_ops_user_id`, because no human opened it: the `exception_type` is `ID_MISMATCH_EXHAUSTED` when the third recorded outcome was `ID_MISMATCH`, and `ATTEMPTS_EXHAUSTED` otherwise. The courier's `ACCEPTED` assignment moves `ACCEPTED → RELEASED`, its `active_delivery_count` drops by one, and it returns `ON_ROUTE → AVAILABLE` at 0. The window's `reserved_slots` drops by one, flipping `FULL → OPEN` where applicable. Critically, the fee allocation stays `ACTIVE` and `PROVISIONAL` and the delivery's `settlement_status` stays `PROVISIONAL`: an exhausted ladder is still billable work, and the money question is left for adjudication or settlement to answer.

**The cold-breach chain.** A forced `COLD_BREACH` produces a four-level transitive cascade in which each level is caused by the one before it, not by the attempt itself. First, the delivery moves `OUT_FOR_DELIVERY → RETURN_PENDING`, `attempt_count` rises by one, and `return_due_at` becomes the clock plus the site's `return_window_minutes`. Second, *because* the delivery entered `RETURN_PENDING` with a cold handling class, an exception case is opened with `exception_type` `COLD_BREACH`, `status` `OPEN`, and a null `opened_by_ops_user_id`. Third, *because* a `COLD_BREACH` case was opened, the delivery's `ACTIVE` fee allocation is set to `VOIDED`, the delivery's `settlement_status` moves `PROVISIONAL → VOIDED`, and its `fee_subtotal_cents` is zeroed — spoiled product is not billed. Fourth, *because* that allocation was voided, its `plan_grant_cents` is subtracted from the pool's `committed_cents`, and the pool returns `EXHAUSTED → ACTIVE` if `remaining_cents` thereby rises above 0. Alongside the chain, the courier's `ACCEPTED` assignment moves to `RELEASED`, its `active_delivery_count` drops with the usual `ON_ROUTE → AVAILABLE` at 0, the window's slot is released with the usual `FULL → OPEN`, and both reliability scores are recomputed with the possibility of an automatic suspension.

**Physical return.** A bag at `RETURN_PENDING` is closed out by the dispensing site confirming it back in hand, which requires the delivery to be `RETURN_PENDING` and the acting operator to own the order's `pharmacy_id`. It advances the delivery `RETURN_PENDING → RETURNED` and the order `DISPATCHED → RETURNED_TO_STOCK`, bumping both versions. When a bag never comes back within `return_due_at`, ops may open a case by hand with `exception_type` `RETURN_OVERDUE`; the other hand-opened types are `DAMAGED` and `LOST_IN_TRANSIT`.

**Changing plans before pickup.** An unpicked delivery — one whose custody is `QUEUED` or `ASSIGNED` — may be moved to another window by the pharmacy operator who owns it or by the patient themselves, by supplying the new `window_id`. The replacement window must sit in the same zone (`ERR_ZONE_MISMATCH`) and must carry the same `courier_mode` as the window the delivery currently holds, since on-demand and scheduled capacity pools are not interchangeable and a bag priced and staffed against one pool cannot be dropped into the other; a mismatch is `ERR_WINDOW_MODE_MISMATCH`. All the reservation-time gates apply again: window not `CLOSED` or `FULL`, zone policy for cold and controlled bags, the elapsed-window and lead-time rule, and `available_slots` of at least 1. On success the old window's `reserved_slots` drops by one with `FULL → OPEN` where applicable, the new window's rises with `OPEN → FULL` where applicable, and both windows bump their `version`. The `ACTIVE` `PROVISIONAL` allocation is superseded and a replacement computed for the new window, which releases the old `plan_grant_cents` from the pool's `committed_cents` and commits the new figure. Any assignment still `OFFERED` or `ACCEPTED` is `REVOKED` with a null `revoked_by_ops_user_id`, the courier is released with the usual count and status adjustment, and an accepted leg additionally walks custody back to `QUEUED` with a null `courier_id`.

**Cancellation.** The same two roles may abandon a delivery whose custody is `QUEUED` or `ASSIGNED`, optionally recording `notes`. Cancellation advances custody to `CANCELLED`, drives `settlement_status` to `VOIDED`, and zeroes `fee_subtotal_cents`; it releases the window slot with `FULL → OPEN` where applicable; it voids the `ACTIVE` allocation and releases its `plan_grant_cents` from the pool's `committed_cents`, returning the pool `EXHAUSTED → ACTIVE` if `remaining_cents` rises above 0; it revokes any assignment that is `OFFERED` or `ACCEPTED` with a null `revoked_by_ops_user_id`, decrementing `active_delivery_count` for an accepted one and returning the courier to `AVAILABLE` at 0; and it drives the order `DISPATCHED → READY` so the bag can be scheduled again — but only when the cancelled delivery is the order's sole delivery whose custody is not `CANCELLED`. Every touched row bumps its `version`. A delivery at `PICKED_UP` or beyond can no longer be cancelled; `ERR_INVALID_CUSTODY_STATE` is the answer.

### 3.7. Courier Reliability, Availability and Suspension

Two scores are computed from the same attempt history and they deliberately disagree, because they answer different questions. Both are recorded to two decimal places, rounded half up, and both read a `reliability_credit` of 1.0 for a `DELIVERED` outcome, 0.5 for `NO_ANSWER`, `REFUSED`, `ADDRESS_INVALID`, or `ID_MISMATCH`, and 0.0 for `COLD_BREACH`. `attempt_total_count` is the number of attempts the courier has ever recorded, and `delivered_count` is the number of them whose `outcome` was `DELIVERED`.

`rolling_reliability_score` is the recency-weighted, partial-credit score that drives selector ranking. Take the courier's most recent attempts, at most three of them — ordered newest first by `created_at`, with `created_at` ascending as the only tie-break — and index them from 0 for the newest. Give the attempt at index *i* a weight of 0.8 raised to the power *i*, so the newest attempt weighs 1, the one before it 0.8, and the one before that 0.64. Multiply each attempt's `reliability_credit` by its weight, sum those products, divide by the sum of the weights used, multiply by 100, and round half up to two decimals. A courier with no attempts at all scores 100.00.

`lifetime_reliability_score` is the unweighted, binary completion rate over the courier's whole history: 100 multiplied by `delivered_count`, divided by `attempt_total_count`, rounded half up to two decimals, and again 100.00 when there are no attempts. There is no recency weighting and no partial credit here — a failed door-step run that earns half credit in the rolling score earns nothing at all in the lifetime score.

Only the lifetime score can suspend anyone. After every recorded attempt, if the courier's `attempt_total_count` has reached 3 or more **and** its `lifetime_reliability_score` is strictly below 60.00 **and** its `status` is `OFFLINE`, `AVAILABLE`, or `ON_ROUTE`, the courier is moved to `SUSPENDED`. The minimum-attempts gate matters: a courier two attempts into a disastrous career is not suspended even at a lifetime score of 0.00. Suspension from `AVAILABLE` removes the courier from the selector candidate set for all future dispatches; suspension from `ON_ROUTE` deliberately leaves any in-flight `ACCEPTED` assignment untouched, so a bag is never abandoned mid-route. Either way the courier's `version` increments.

Availability is otherwise the courier's own business. Submitting a `target_status` of `AVAILABLE` while `OFFLINE` puts the courier on shift; submitting `OFFLINE` while `AVAILABLE` takes them off, but only when `active_delivery_count` is 0 — trying to go dark while holding accepted work is `ERR_INVALID_COURIER_STATE`. The `OFFLINE → AVAILABLE → OFFLINE` cycle may be repeated freely. `AVAILABLE → ON_ROUTE` and `ON_ROUTE → AVAILABLE` are never client-driven; the first happens when an offer is accepted and the second when the courier's last `ACCEPTED` assignment stops being `ACCEPTED`, whether it became `COMPLETED`, `RELEASED`, or `REVOKED`.

`NetworkOps` may also submit a `target_status` of `SUSPENDED` for a courier that is `OFFLINE`, `AVAILABLE`, or `ON_ROUTE`. Only `NetworkOps` may lift a suspension, by submitting `AVAILABLE` for a courier whose `status` is `SUSPENDED`; a `Courier` attempting to clear its own `SUSPENDED` status is rejected with `ERR_INVALID_COURIER_STATE`. Reinstatement closes the `AVAILABLE → SUSPENDED → AVAILABLE` cycle. Every availability change bumps the courier's `version`.

### 3.8. Exception Adjudication: Reship, Credit or Denial

Cases arrive two ways. The attempt cascades of §3.6 open them automatically with a null `opened_by_ops_user_id`. A human may also open one by supplying the `delivery_id`, an `exception_type` of `COLD_BREACH`, `ID_MISMATCH_EXHAUSTED`, `ATTEMPTS_EXHAUSTED`, `DAMAGED`, `LOST_IN_TRANSIT`, or `RETURN_OVERDUE`, and optional `notes`. A hand-opened case starts at `OPEN`, and `opened_by_ops_user_id` records the acting `X-User-ID` only when the caller is `NetworkOps`; a case opened by a `PharmacyOperator` leaves it null, exactly as a system-opened one does. A case cannot be opened against a delivery whose custody is `CANCELLED` — a cancelled delivery has nothing left to except — and that rejection is `ERR_INVALID_CUSTODY_STATE`.

Adjudication is a two-step ritual and the review step cannot be skipped: an `OPEN` case must first be taken up, moving it `OPEN → UNDER_REVIEW`, and only an `UNDER_REVIEW` case may be adjudicated. Adjudicating straight out of `OPEN`, or reviewing a case that is not `OPEN`, is `ERR_INVALID_EXCEPTION_STATE`.

Every adjudication carries a `disposition` of `RESHIP`, `CREDIT`, or `DENY`, the `expected_delivery_version` demanded by §2.7, an optional `reship_window_id`, and optional `notes`. Two guards apply to all three dispositions alike. The acting operator must be neither the case's `opened_by_ops_user_id`, where that field is non-null, nor the `revoked_by_ops_user_id` of any assignment on the case's delivery; either collision is `ERR_SEGREGATION_OF_DUTIES`. A system-opened case is therefore adjudicable by any operations user who did not personally revoke a courier off that delivery. And the delivery's `settlement_status` must still be `PROVISIONAL`, or the adjudication is `ERR_INVALID_SETTLEMENT_STATE` — which is what keeps an already-settled, already-waived, or already-voided delivery out of the adjudication path entirely. Whichever branch is taken, `adjudicated_by_ops_user_id` records the acting `X-User-ID` and both the case and the delivery bump their `version`.

**Branch A — `RESHIP`.** This is the physically compensating branch and it moves the case `UNDER_REVIEW → RESHIP_AUTHORIZED`. It additionally requires the delivery's custody to be `RETURN_PENDING` or `RETURNED`, and a `reship_window_id` naming a window that is `OPEN`, sits in the same `zone_id` as the original window, carries the same `courier_mode` as the original window, and has `available_slots` of at least 1. A missing `reship_window_id`, or a delivery already linked to a reship, is `ERR_OVERRIDE_ADJUDICATION_CONFLICT`; a wrong zone is `ERR_ZONE_MISMATCH`; a wrong mode is `ERR_WINDOW_MODE_MISMATCH`; a window with no room is `ERR_WINDOW_FULL`. One delivery may spawn at most one reship, and because a reship delivery on the same order is itself a live delivery, a *second* reship attempt on that order trips `ERR_DUPLICATE_ACTIVE_DELIVERY` ahead of the weaker reship-conflict rule.

The branch then runs its own four-level cascade. First, a new delivery is created for the same `order_id`, pointing at the `reship_window_id`, with `reship_of_delivery_id` set to the original delivery, `custody_status` `QUEUED`, and `settlement_status` `PROVISIONAL`. Second, *because* that reship delivery was created, a `PROVISIONAL` allocation is computed for it exactly as in §3.3, with `billable_attempts` pinned to 1. Third, *because* that allocation was created, its `plan_grant_cents` is added to the pool's `committed_cents`. Fourth, *because* `committed_cents` rose, the pool moves `ACTIVE → EXHAUSTED` if `remaining_cents` reaches 0. Alongside, the target window's `reserved_slots` rises by one with `OPEN → FULL` at capacity, and the case's `reship_delivery_id` records the new delivery. The original delivery's `version` increments because its reship linkage changed. The grant-applicability and Medicaid-coverage rules of §3.3 apply to the new allocation, so a reship can fail with `ERR_GRANT_NOT_APPLICABLE` or `ERR_GRANT_COVERAGE_INSUFFICIENT` just as an original reservation can.

**Branch B — `CREDIT`.** This is the exact mirror image: financially compensating and physically inert. It moves the case `UNDER_REVIEW → CREDIT_ISSUED` and requires the delivery's `settlement_status` to be `PROVISIONAL`. The delivery's settlement moves `PROVISIONAL → WAIVED`, the `ACTIVE` allocation is set to `VOIDED`, the delivery's `fee_subtotal_cents` is zeroed, the voided `plan_grant_cents` is released from the pool's `committed_cents` with the pool returning `EXHAUSTED → ACTIVE` if `remaining_cents` rises above 0, and the case's `credit_cents` records the `fee_subtotal_cents` of the allocation that was just voided. No reship delivery is created and no window slot is reserved.

**Branch C — `DENY`.** The network accepts no liability, and this branch is the deliberate null of the other two: neither financially nor physically compensating. The case moves `UNDER_REVIEW → DENIED` and `credit_cents` is set to 0. Nothing else changes anywhere in the system. No reship delivery is created, so the case's `reship_delivery_id` stays null and no window's `reserved_slots` moves. The delivery's `ACTIVE` fee allocation is left `ACTIVE` and `PROVISIONAL`, its `fee_subtotal_cents` untouched, and the grant pool's `committed_cents`, `remaining_cents`, and `status` all stand as they were. Above all, the delivery's `settlement_status` is deliberately left at `PROVISIONAL` rather than being driven to `WAIVED`, precisely so that ordinary settlement can proceed afterwards and bill the work that was in fact performed.

All three branches re-join at a single terminus. A case whose `status` is `RESHIP_AUTHORIZED`, `CREDIT_ISSUED`, or `DENIED` is closed, moving it to `CLOSED` and bumping its `version`; `CLOSED` is terminal, and closing from any other state is `ERR_INVALID_EXCEPTION_STATE`.

### 3.9. Settlement and the Disclosure Audit Trail

Settlement is the only operation that advances the money dimension to its normal terminus, and only `NetworkOps` may run it. It requires the delivery's `settlement_status` to still be `PROVISIONAL`, its `custody_status` to be `DELIVERED` or `RETURNED` — anything earlier is `ERR_INVALID_CUSTODY_STATE`, since the physical question must be answered before the financial one — and no exception case on that delivery to be `OPEN` or `UNDER_REVIEW`, since money may not be finalised while an exception is live; a pending case is `ERR_EXCEPTION_PENDING`.

Settlement rebuilds the bill rather than accepting the provisional one. The `PROVISIONAL` allocation is set to `SUPERSEDED` and its `plan_grant_cents` is released from the pool's `committed_cents`. A fresh allocation is then computed with `variant` `FINAL` and `status` `ACTIVE`, using the very same six-line construction, per-line rounding, and payer-mix waterfall described in §3.3 — with one difference, and it is the whole point of the variant. On a final bill, *billable attempts* is no longer pinned to 1: it becomes the delivery's `attempt_count`, or 1 if no run was ever recorded. Two lines therefore move. `cold_pack_line_cents` becomes the zone's `cold_pack_fee_cents` multiplied by that count, because each run consumed a fresh re-ice; and `reattempt_line_cents` stops being zero, charging 400 cents for each run beyond the first, capped at two such units. The four other lines are unchanged: `base_line_cents`, `mileage_line_cents`, `controlled_line_cents`, and `after_hours_line_cents` are charged exactly once however many runs were made. A provisional bill therefore always shows exactly one cold-pack re-ice and no re-attempt surcharge; the delta between the two variants is entirely attributable to those two lines.

The new allocation's `plan_grant_cents` is added to the pool's `consumed_cents` and the pool's `remaining_cents` and `status` are recomputed — note that the pool's exposure moves from committed to consumed in a single request, so a settlement that costs the same as the provisional estimate leaves `remaining_cents` untouched. The delivery's `settlement_status` moves `PROVISIONAL → FINALIZED`, its `fee_subtotal_cents` mirrors the final allocation's, and its `custody_status` does not move at all — it stays `DELIVERED` or `RETURNED`. When custody is `DELIVERED`, the order moves `DISPATCHED → CLOSED`; a `RETURNED` delivery leaves the order at the `RETURNED_TO_STOCK` value the return confirmation already gave it. The grant-applicability and Medicaid full-coverage rules apply to the final allocation exactly as they do to a provisional one, so settlement can fail with `ERR_GRANT_NOT_APPLICABLE` or `ERR_GRANT_COVERAGE_INSUFFICIENT`. Delivery, allocation, pool, and order each bump their own `version`.

Reading the ledger is deliberately broad. A `PlanAdministrator` may read its own pools with their live `committed_cents`, `consumed_cents`, and `remaining_cents`, and may read the allocations drawn against them with the full line vector — `base_line_cents`, `mileage_line_cents`, `cold_pack_line_cents`, `controlled_line_cents`, `after_hours_line_cents`, `reattempt_line_cents`, `fee_subtotal_cents`, `cost_share_pct_applied`, `patient_gross_share_cents`, `plan_grant_cents`, `absorption_tier_cents`, `pharmacy_absorption_cents`, `patient_payable_cents`, and `pharmacy_payable_cents` — including `SUPERSEDED` and `VOIDED` history. A pharmacy operator sees the same allocations for its own bags. Individual door-step attempt records are readable by the courier who made them, the pharmacy behind the bag, and ops; they are the raw input of both reliability variants and are never modified after they are written.

Finally, the disclosure trail. Whenever a courier is shown the courier-limited projection of §2.11 — or an operations user previews that same view, in which case the logged `courier_id` is null — a disclosure row is appended with a `purpose` of `ROUTING` or `DELIVERY_EXECUTION`, defaulting to `DELIVERY_EXECUTION` when the caller does not say. A courier that holds no assignment on the delivery, current or historical, is refused with `ERR_HIPAA_SCOPE_VIOLATION` and no row is written. The trail is then readable from both directions: by courier, listing every projection that courier has been shown, and by delivery, listing every courier who has been shown that bag's protected data. Neither read discloses anything the projection itself withholds.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering reference data, taking in an order, reserving a delivery, creating a courier offer, recording a door-step attempt, opening an exception case — return `201 Created`. Operations that modify an existing resource, run a sweep, move the clock, or read data return `200 OK`. Every collection is mounted at the top level; no path expresses ownership nesting, and the only nested paths are the HIPAA and audit projections.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/health-plans` | Register a payer and its member cost-share percentage | NetworkOps |
| POST | `/plan-grants` | Fund a delivery-fee subsidy pool for one plan and benefit year | PlanAdministrator, NetworkOps |
| POST | `/pharmacies` | Register a dispensing site with its cold-chain and controlled-substance credentials | NetworkOps |
| POST | `/delivery-zones` | Define a serviced zone and its fee schedule | NetworkOps |
| POST | `/patients` | Register a delivery recipient | PharmacyOperator, NetworkOps |
| POST | `/patients/{id}/consent` | Record or revoke the patient's HIPAA delivery-disclosure consent | Patient, PharmacyOperator |
| POST | `/couriers` | Onboard a courier with mode, served zones and handling certifications | NetworkOps |
| POST | `/couriers/{id}/status` | Move a courier between OFFLINE, AVAILABLE and SUSPENDED | Courier, NetworkOps |
| POST | `/delivery-windows` | Publish a capacity window for one zone and courier mode | NetworkOps |
| POST | `/pharmacy-orders` | Intake a filled prescription bundle awaiting delivery | PharmacyOperator |
| POST | `/pharmacy-orders/{id}/mark-ready` | Release the order for delivery scheduling | PharmacyOperator |
| POST | `/pharmacy-orders/{id}/hold` | Pull a READY order back to INTAKE for re-verification | PharmacyOperator |
| POST | `/deliveries` | Reserve a window slot for a READY order and price it provisionally | PharmacyOperator |
| POST | `/deliveries/{id}/reschedule` | Move an unpicked delivery to another window in the same zone and mode | PharmacyOperator, Patient |
| POST | `/deliveries/{id}/cancel` | Abandon a delivery before pickup and reverse every reservation it made | PharmacyOperator, Patient |
| POST | `/deliveries/{id}/dispatch` | Offer the delivery to a courier — selected by policy, or to an explicitly named courier | NetworkOps |
| POST | `/courier-assignments/{id}/accept` | Courier accepts an outstanding offer and takes the delivery | Courier |
| POST | `/courier-assignments/{id}/decline` | Courier turns down an offer, excluding itself from re-selection on that delivery | Courier |
| POST | `/courier-assignments/{id}/revoke` | Ops pulls an offer or an accepted leg back from a courier | NetworkOps |
| POST | `/deliveries/{id}/pickup` | Courier takes custody at the pharmacy counter | Courier |
| POST | `/deliveries/{id}/depart` | Courier leaves for the patient's address, on the first run or on a ladder re-attempt | Courier |
| POST | `/deliveries/{id}/attempts` | Record the outcome of one door-step run, with proof-of-delivery capture | Courier |
| POST | `/deliveries/{id}/confirm-return` | Pharmacy confirms physical receipt of an undelivered bag | PharmacyOperator |
| POST | `/deliveries/{id}/settle` | Finalize the money dimension, replacing the provisional bill with the FINAL variant | NetworkOps |
| POST | `/exception-cases` | Open an exception on a delivery by hand | NetworkOps, PharmacyOperator |
| POST | `/exception-cases/{id}/start-review` | Ops takes the case up for adjudication | NetworkOps |
| POST | `/exception-cases/{id}/adjudicate` | Fork the case into a reship, a fee credit, or a denial | NetworkOps |
| POST | `/exception-cases/{id}/close` | Join the three adjudication branches back into CLOSED | NetworkOps |
| POST | `/routing-runs` | Sweep expired offers and elapsed windows, then offer every unassigned QUEUED delivery | NetworkOps |
| POST | `/_clock/set_current_utc` | Set the logical clock that every temporal rule reads | NetworkOps |
| GET | `/plan-grants/{id}` | Read one grant pool with its live commitment ledger | PlanAdministrator, NetworkOps |
| GET | `/plan-grants` | List grant pools | PlanAdministrator, NetworkOps |
| GET | `/delivery-windows/{id}` | Read one capacity window with occupancy | PharmacyOperator, Patient, Courier, NetworkOps |
| GET | `/delivery-windows` | List capacity windows | PharmacyOperator, Patient, Courier, NetworkOps |
| GET | `/pharmacy-orders/{id}` | Read one order | PharmacyOperator, Patient, NetworkOps |
| GET | `/pharmacy-orders` | List orders | PharmacyOperator, Patient, PlanAdministrator, NetworkOps |
| GET | `/couriers/{id}` | Read one courier with both reliability scores | Courier, NetworkOps |
| GET | `/couriers/{id}/disclosures` | Audit trail of every PHI projection this courier has been shown | Courier, NetworkOps |
| GET | `/deliveries/{id}` | Read one delivery with both state dimensions and the full PHI payload | PharmacyOperator, Patient, PlanAdministrator, NetworkOps |
| GET | `/deliveries` | List deliveries with filters over both state dimensions and every relationship | PharmacyOperator, Patient, PlanAdministrator, NetworkOps |
| GET | `/deliveries/{id}/courier-view` | HIPAA minimum-necessary projection of a delivery for the assigned courier | Courier, NetworkOps |
| GET | `/deliveries/{id}/disclosures` | Audit trail of every courier who has been shown this delivery's PHI | PharmacyOperator, Patient, NetworkOps |
| GET | `/courier-assignments/{id}` | Read one offer or accepted leg | Courier, NetworkOps |
| GET | `/courier-assignments` | List assignments | Courier, NetworkOps |
| GET | `/delivery-attempts/{id}` | Read one immutable door-step attempt record | Courier, PharmacyOperator, NetworkOps |
| GET | `/delivery-attempts` | List attempts, the raw input of both reliability variants | Courier, PharmacyOperator, NetworkOps |
| GET | `/fee-allocations/{id}` | Read one payer-mix allocation with its full line vector | PharmacyOperator, PlanAdministrator, NetworkOps |
| GET | `/fee-allocations` | List allocations, including superseded and voided history | PharmacyOperator, PlanAdministrator, NetworkOps |
| GET | `/exception-cases/{id}` | Read one exception case with its disposition and reship link | NetworkOps, PharmacyOperator, PlanAdministrator |
| GET | `/exception-cases` | List exception cases | NetworkOps, PharmacyOperator, PlanAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_PHARMACY_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_PATIENT_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_COURIER_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_PLAN_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_HIPAA_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_COURIER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXCEPTION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_READY` | 409 Conflict |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_CUSTODY_STATE` | 409 Conflict |
| `ERR_INVALID_SETTLEMENT_STATE` | 409 Conflict |
| `ERR_INVALID_ASSIGNMENT_STATE` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_INVALID_EXCEPTION_STATE` | 409 Conflict |
| `ERR_COURIER_SUSPENDED` | 409 Conflict |
| `ERR_COURIER_UNAVAILABLE` | 409 Conflict |
| `ERR_INVALID_COURIER_STATE` | 409 Conflict |
| `ERR_WINDOW_CLOSED` | 409 Conflict |
| `ERR_GRANT_NOT_APPLICABLE` | 409 Conflict |
| `ERR_STALE_WINDOW_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DELIVERY_VERSION` | 412 Precondition Failed |
| `ERR_CONSENT_NOT_GRANTED` | 409 Conflict |
| `ERR_CONTROLLED_NOT_LICENSED` | 409 Conflict |
| `ERR_CONTROLLED_ZONE_PROHIBITED` | 409 Conflict |
| `ERR_COLD_CHAIN_UNSUPPORTED_ZONE` | 409 Conflict |
| `ERR_COURIER_NOT_COLD_CERTIFIED` | 409 Conflict |
| `ERR_COURIER_NOT_CONTROLLED_CERTIFIED` | 409 Conflict |
| `ERR_COURIER_ZONE_NOT_SERVED` | 409 Conflict |
| `ERR_COURIER_MODE_MISMATCH` | 409 Conflict |
| `ERR_COLD_SEAL_REQUIRED` | 409 Conflict |
| `ERR_SIGNATURE_REQUIRED` | 409 Conflict |
| `ERR_UNATTENDED_NOT_PERMITTED` | 409 Conflict |
| `ERR_ID_VERIFICATION_INSUFFICIENT` | 409 Conflict |
| `ERR_ZONE_NOT_SERVICED` | 409 Conflict |
| `ERR_ZONE_MISMATCH` | 409 Conflict |
| `ERR_WINDOW_MODE_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_DELIVERY` | 409 Conflict |
| `ERR_MAX_HOLDS_EXCEEDED` | 409 Conflict |
| `ERR_WINDOW_ELAPSED` | 409 Conflict |
| `ERR_WINDOW_INTERVAL_INVALID` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COURIER_OVERLAP_CONFLICT` | 409 Conflict |
| `ERR_REATTEMPT_COOLDOWN_ACTIVE` | 409 Conflict |
| `ERR_WINDOW_FULL` | 409 Conflict |
| `ERR_NO_ELIGIBLE_COURIER` | 409 Conflict |
| `ERR_GRANT_COVERAGE_INSUFFICIENT` | 409 Conflict |
| `ERR_EXCEPTION_PENDING` | 409 Conflict |
| `ERR_OVERRIDE_ADJUDICATION_CONFLICT` | 409 Conflict |
