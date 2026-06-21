# Durable Medical Equipment API — Product Requirements Document

## 1. Introduction

Durable Medical Equipment (DME) suppliers operate at the intersection of clinical certification, Medicare fee-schedule pricing, and payer-side audit. A single piece of equipment — a CPAP device, a wheelchair, an oxygen concentrator — can be rented month over month, purchased outright, or rented under a Medicare "capped rental" arrangement that automatically converts to beneficiary ownership after a fixed number of billed months. Each of these paths carries its own paperwork: a Certificate of Medical Necessity signed by a physician, a prior authorization granted by a payer, a proof-of-delivery signature captured at setup, and a stream of monthly billing cycles that must reconcile exactly against an order-level ledger. When any of that paperwork is missing or defective, the payer may open an audit and claw back amounts that were already billed or paid.

This document specifies a REST API that models that whole lifecycle as a set of flat, peer-level resource collections. The central business object is the **DME order**, which references a patient, a supplier, and a catalogued HCPCS item; every other lifecycle record — the certificate, the authorization, the delivery, the rental cycles, the claim lines, the CPAP resupply requests, and the audits — carries a foreign key back to the order rather than nesting beneath it in the URL. The system is, at its core, a ledger-reconciliation engine wrapped in compliance gates: it must compute allowed amounts precisely to the cent, enforce the order of validation so that the most specific defect surfaces first, and keep the order's running total exactly equal to the sum of its live claim lines through every cascade — delivery, cap conversion, and audit recoupment alike.

The intended readers are the engineers who will implement the service. The prose below favors the domain narrative; the precise structural contract (envelopes, pagination, concurrency, error codes) is concentrated in Section 2, and the business workflows are developed in Section 3. Endpoint and error tables in Sections 4 and 5 are intentionally thin — they index the behavior described in the narrative rather than restating it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two HTTP headers: `X-User-ID`, identifying the calling actor, and `X-User-Role`, naming the role under which the call is made. If either header is missing or invalid, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is always evaluated before authorization, and both are evaluated before the existence of any referenced resource is checked.

There are exactly four roles, spelled precisely as follows: `PlatformAdmin`, `SupplierUser`, `PhysicianUser`, and `PayerReviewer`.

`PlatformAdmin` is an operator that curates reference data — registering patients, registering and amending suppliers, and adding catalog items — and controls the deterministic system clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for traceability but never compares it to any entity's `id`.

`SupplierUser` is DME supplier staff who own orders, deliveries, rental cycles, CPAP resupply requests, and who open prior-authorization requests. When `X-User-Role` is `SupplierUser`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's supplier foreign key to `X-User-ID`.

`PhysicianUser` is the certifying physician who authors, activates, and revokes Certificates of Medical Necessity. When `X-User-Role` is `PhysicianUser`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, the physician is also named by the `physician_npi` written onto the certificate) but does not compare `X-User-ID` to any entity's `id`.

`PayerReviewer` is payer-side staff who decide prior authorizations, mark rental cycles paid, and open, uphold, or dismiss audits. When `X-User-Role` is `PayerReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The specific operations each role may invoke are summarized in the authorized-role column of Section 4; the prose of Section 3 names the acting role for each transition as it arises.

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

List endpoints accept two pagination query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, has a minimum accepted value of 1 and a maximum accepted value of 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are always sorted by `created_at` in ascending order before the offset and limit are applied. For every list response, the `meta` object additionally carries `limit`, `offset`, `total_count` (the count of records matching the filter before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. The full set of business resources in this system — Patient, Supplier, HCPCSItem, DMEOrder, CMN, PriorAuthorization, Delivery, RentalBillingCycle, ClaimLine, CPAPResupplyOrder, and Audit — additionally carry an `updated_at` timestamp (also ISO 8601 UTC with three fractional digits) and an integer `version`. The `version` begins at 1 when the resource is created and increments by 1 on every mutation that changes the resource; `updated_at` is refreshed to the current clock instant on each such mutation. Whenever a side effect described in Section 3 mutates a resource — a status change, a recomputed ledger total, a superseding cascade — that resource's `version` is incremented and its `updated_at` refreshed.

### 2.5. The Deterministic Clock

Timing in this system is not read from wall-clock time; it is read from a server-controlled logical clock so that rental anchoring, prior-authorization expiry, resupply spacing, and delivery stamps are all reproducible. A `PlatformAdmin` may advance this clock by supplying a target instant in the `to_iso8601` field; the clock then reports that instant as "now." Every timestamp the system stamps from "the clock" — an order's `ordered_at_utc`, a delivery's `delivered_at_utc`, a resupply's `requested_at_utc`, an authorization's `expires_at_utc` — is read from this logical clock at the moment of the operation.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and exchanged as integer cents. Where a calculation produces a fractional cent, it is resolved by rounding half up to a whole cent — that is, a residual of exactly half a cent rounds away from zero to the next whole cent. Counts (such as the number of billed rental months or the number of recouped cycles) are plain integers. The rounding discipline matters for the recoupment total in particular: each recouped cycle is rounded to whole cents first and the rounded per-cycle amounts are then summed, rather than summing first and rounding once at the end.

### 2.7. Order-Level Ledger Integrity

The DME order acts as a ledger. Its `total_allowed_cents` is always the sum of `allowed_amount_cents` across all of the order's claim lines whose status is not `VOID`; recoupment lines participate in this sum as negative amounts. This total is recomputed every time a claim line is created or voided, every time a rental cycle is billed or recouped, and every time an audit is upheld. The invariant the system must preserve is that after any such event — including the full audit recoupment cascade — the order's `total_allowed_cents` equals the sum of `allowed_amount_cents` over its non-`VOID` claim lines, with no drift.

### 2.8. Nested Reference Resolution and Validation Ordering

Although the URL topology is flat — every collection is a root-level peer — a single request often references several resources at once (an order, plus the certificate or delivery or cycle or audit acting on it, plus the order's patient, supplier, and catalog item by foreign key). When any referenced resource does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Existence is validated left to right: the primary resource named in the path first, then the lifecycle resource it acts on (certificate, delivery, cycle, audit, or resupply), then the foreign-key targets (patient, then supplier, then catalog item).

The system evaluates checks in a fixed priority so that the most specific defect surfaces rather than being masked by a generic one. The global order is: authentication (`ERR_UNAUTHENTICATED`) first; then authorization (`ERR_FORBIDDEN`); then existence of referenced resources (`ERR_NOT_FOUND`); then the generic state precondition for the requested transition (`ERR_INVALID_STATE`); then the domain-specific business rules; and finally request well-formedness for any create-or-transition endpoint that carries a body (`ERR_INVALID_REQUEST`, raised when a required field is absent, an enum value is out of its allowed set, or a numeric value falls outside its stated bounds) and uniqueness of registration fields (`ERR_DUPLICATE_VALUE`). Two deliberate exceptions to the "generic state check first" rule are described where they apply: the rental-cap check on cycle posting (Section 3.5) and the stale-version check relative to the signed-date check on certificate activation (Section 3.3).

### 2.9. Optimistic Concurrency on Certificate Activation

Activating a Certificate of Medical Necessity is the one operation guarded by optimistic concurrency against the order it certifies. The activation request must carry an `expected_order_version` field whose value is the order `version` the client last observed. If that value does not match the target order's current `version`, the activation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). Because a successful activation increments the order's `version`, a second activation request still carrying the previously observed version is necessarily stale and is rejected on this rule — this is how the system serializes competing certificate activations on the same order without depending on requests overlapping in time. No other endpoint accepts or requires a version field.

### 2.10. Uniqueness Constraints

Three reference fields are unique across their collections: a patient's `medicare_id` (the Medicare beneficiary identifier), a supplier's `ptan` (Provider Transaction Access Number), and a catalog item's `hcpcs_code`. An attempt to register a second patient, supplier, or catalog item reusing one of these values is rejected with `ERR_DUPLICATE_VALUE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Reference Data: Patients, Suppliers, and the HCPCS Catalog

Before any order can exist, a `PlatformAdmin` populates three reference collections. A **patient** (the Medicare beneficiary) is registered with a `full_name`, a `medicare_id`, a `date_of_birth` given as an ISO date in `YYYY-MM-DD` form, and an `address_state` given as a two-letter US state code. A **supplier** is registered with its legal `name`, its `ptan`, and an `accreditation_active` flag indicating whether it is currently Medicare-accredited; when the flag is omitted at registration it defaults to true. A `PlatformAdmin` may later amend a supplier's `accreditation_active` flag through the supplier-update capability — this is the business surface through which accreditation lapses and reinstatements are recorded.

A **catalog item** represents one HCPCS-coded device and is registered with its `hcpcs_code`, a plain-language `description`, a `billing_category`, a `purchase_price_cents` (the allowed lump-sum purchase price per the Medicare fee schedule), a `monthly_rental_cents` (the allowed monthly rental amount before any modifier adjustment), and three boolean flags: `requires_cmn`, `requires_prior_auth`, and `is_cpap`. Each of the three flags defaults to false when omitted. The `billing_category` is one of `CAPPED_RENTAL`, `INEXPENSIVE_ROUTINE`, `PURCHASE_ONLY`, or `OXYGEN`, and it drives which billing algorithm and which cap apply to any order placed against the item. The `requires_cmn` flag marks an item that may not be delivered until a certificate of medical necessity is active; `requires_prior_auth` marks an item that may not be delivered until a payer authorization is approved and unexpired; and `is_cpap` is true only for the CPAP device and is what gates whether CPAP resupply requests may be opened against an order.

### 3.2. Creating and Cancelling a DME Order

A `SupplierUser` opens the lifecycle by creating a **DME order**, supplying the `patient_id`, the `supplier_id` of the fulfilling supplier, the `hcpcs_item_id` of the catalogued device, an `acquisition_type`, an optional `modifier`, and the `ordered_at_utc` order timestamp. The `acquisition_type` is either `RENTAL` or `PURCHASE`, and it must be consistent with the item's billing category: items categorized `CAPPED_RENTAL`, `OXYGEN`, or `INEXPENSIVE_ROUTINE` must be ordered as `RENTAL`, while `PURCHASE_ONLY` items must be ordered as `PURCHASE`. A mismatch is rejected with `ERR_ACQUISITION_TYPE_MISMATCH`. The `modifier` is one of `NONE`, `NU` (new purchase), or `KX` (medical-policy met); when omitted it defaults to `NONE`. The `ordered_at_utc` timestamp is clock-stamped and becomes the anchor from which rental cycle periods are measured.

A newly created order is born in `DRAFT` status, with `rental_months_billed` initialized to 0, `cap_reached` initialized to false, and `total_allowed_cents` initialized to 0. From `DRAFT`, the order may move forward to `READY_FOR_DELIVERY`, or it may be abandoned. Cancelling is available only while the order is still in `DRAFT`; a cancel request against an order in any other status is rejected with `ERR_INVALID_STATE`. When a `SupplierUser` cancels a `DRAFT` order, the order moves to the terminal `CANCELLED` status, and two cleanup cascades fire: every certificate for that order that is in `DRAFT` or `ACTIVE` status is moved to `REVOKED`, and every delivery for that order that is in `SCHEDULED` status is moved to `CANCELLED`.

A `SupplierUser`, `PayerReviewer`, or `PlatformAdmin` may retrieve a single order — which is returned with its computed ledger fields (`rental_months_billed`, `cap_reached`, and `total_allowed_cents`) populated — and the same three roles may list orders, optionally filtering by `patient_id`, `supplier_id`, `hcpcs_item_id`, or `status`.

### 3.3. The Certificate of Medical Necessity

A `PhysicianUser` authors a **Certificate of Medical Necessity** (CMN) for an order by supplying the `order_id` it supports, the certifying physician's `physician_npi`, a `length_of_need_months` value (the certified months of medical need, an integer from 1 to 99, where 99 denotes lifetime need), and a `signed_date` (the ISO date the physician signed). A new certificate is created in `DRAFT` status with its `superseded_by_id` unset.

A physician activates a draft certificate to make it the governing certificate for its order. Activation requires that the certificate currently be in `DRAFT` status, otherwise the request is rejected with `ERR_INVALID_STATE`. Two further conditions apply, and their ordering is deliberate. First, the certificate's `signed_date` must be on or before the calendar date of the order's `ordered_at_utc`; a certificate signed after the order was placed is rejected with `ERR_CMN_SIGNED_AFTER_ORDER`. Second, the activation must carry an `expected_order_version` that matches the order's current `version`, failing which it is rejected with `ERR_STALE_ORDER_VERSION`. The signed-date check is evaluated before the version check, so that a certificate signed after the order surfaces `ERR_CMN_SIGNED_AFTER_ORDER` even in the case where the supplied version is also stale.

A successful activation moves the certificate from `DRAFT` to `ACTIVE`. The system guarantees that an order has at most one active certificate at a time: if another certificate on the same order is already `ACTIVE` at the moment of activation, that prior certificate is superseded — its `superseded_by_id` is set to the `id` of the newly activated certificate and its status moves from `ACTIVE` to the terminal `SUPERSEDED` state — so that the count of active certificates on the order remains exactly one. Activation also increments the order's `version` by 1, which is precisely the side effect that renders any concurrently held, pre-activation order version stale for a subsequent activation (see Section 2.9).

A physician may also revoke a certificate that is currently `ACTIVE`, moving it to the terminal `REVOKED` status; revoking a certificate that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. Certificates may be retrieved individually or listed by a `PhysicianUser`, `SupplierUser`, or `PayerReviewer`, with the list filterable by `order_id`, by `superseded_by_id` (to find the certificate a given certificate replaced), or by `status`.

### 3.4. Prior Authorization

For items that require payer sign-off before delivery, a `SupplierUser` opens a **prior authorization** request by supplying the `order_id` and a free-text `payer_reference`. The request begins in `PENDING` status. A `PayerReviewer` then decides it: approval moves it from `PENDING` to `APPROVED`, and denial moves it from `PENDING` to `DENIED`; in either case a request that is not `PENDING` is rejected with `ERR_INVALID_STATE`. The reviewer may attach a `decision_reason` on either decision, and whatever reason is supplied is captured onto the authorization. On approval, the authorization's `expires_at_utc` is set to the clock's current instant plus 60 days.

An approved authorization does not remain valid forever. Whenever the delivery-readiness gate is evaluated (Section 3.6), an authorization that is `APPROVED` but whose `expires_at_utc` is at or before the clock's current instant is treated as `EXPIRED` and no longer satisfies the gate. Authorizations may be retrieved individually or listed by a `SupplierUser` or `PayerReviewer`, filterable by `order_id` or `status`.

### 3.5. Delivery and Proof of Delivery

A `SupplierUser` schedules a **delivery** (the physical delivery and setup of the equipment) by supplying the `order_id`, a `scheduled_for_utc` time, and optionally a `pod_signature_name`. The delivery is created in `SCHEDULED` status, with `pod_received` false and `delivered_at_utc` unset. From `SCHEDULED`, a delivery may be confirmed, failed, or cancelled; each of these requires that the delivery currently be `SCHEDULED`, otherwise `ERR_INVALID_STATE` applies.

Confirming a delivery is the proof-of-delivery step. The confirm request must carry a non-empty `pod_signature_name` (the name of the person who signed for the equipment); an empty or absent signature is rejected with `ERR_POD_SIGNATURE_REQUIRED`. Confirmation also requires that the order be in `READY_FOR_DELIVERY` status — a confirm against an order in any other status is rejected with `ERR_INVALID_STATE`. On a successful confirm, the delivery moves to the terminal `CONFIRMED` status, its `pod_received` flag is set to true, and its `delivered_at_utc` is stamped from the clock. The confirmation then bubbles up to the order: the order advances from `READY_FOR_DELIVERY` to `DELIVERED`. Failing a scheduled delivery moves it to the terminal `FAILED` status with no further effect, and cancelling a scheduled delivery moves it to the terminal `CANCELLED` status with no further effect. Deliveries may be retrieved individually or listed by a `SupplierUser` or `PayerReviewer`, filterable by `order_id` or `status`.

### 3.6. Readying an Order, Activating Billing, and the Purchase Line

Moving an order from `DRAFT` to `READY_FOR_DELIVERY` is the compliance checkpoint. A `SupplierUser` requests this transition, which requires the order to be in `DRAFT` status (`ERR_INVALID_STATE` otherwise) and then enforces three business gates, evaluated in the order given here. First, if the ordered item requires a certificate of medical necessity, an `ACTIVE` certificate must exist for the order, failing which the transition is rejected with `ERR_CMN_REQUIRED`. Second, if the ordered item requires prior authorization, an authorization for the order must be in `APPROVED` status with an `expires_at_utc` strictly after the clock's current instant, failing which the transition is rejected with `ERR_PRIOR_AUTH_REQUIRED`; an approved-but-expired authorization does not satisfy this gate. The certificate gate is evaluated before the prior-authorization gate. Third, the fulfilling supplier must be currently accredited — its `accreditation_active` flag must be true — failing which the transition is rejected with `ERR_SUPPLIER_NOT_ACCREDITED`. When all applicable gates pass, the order advances to `READY_FOR_DELIVERY`.

Once at least one delivery has confirmed and bubbled the order up to `DELIVERED`, a `SupplierUser` activates billing, moving the order from `DELIVERED` to `ACTIVE`. This requires the order to be in `DELIVERED` status (`ERR_INVALID_STATE` otherwise) and additionally requires that at least one delivery for the order be `CONFIRMED` with its `pod_received` flag true; absent such a delivery the activation is rejected with `ERR_NO_PROOF_OF_DELIVERY`. Activating billing has a branch by acquisition type. For a `PURCHASE` order, activation posts the order's single purchase claim line: one claim line of type `PURCHASE` is created with its allowed amount computed as described below, and the order's `total_allowed_cents` is then recomputed. For a `RENTAL` order, no claim line is posted at activation — rental orders begin accruing monthly cycles only after they are `ACTIVE`.

The **purchase allowed amount** for the purchase claim line is derived from the item's `purchase_price_cents` and the order's `modifier`. When the modifier is `NU`, the full fee schedule is allowed — the allowed amount equals `purchase_price_cents` exactly. For any other modifier value, the equipment is paid at the used-equipment rate, which is 75 percent of `purchase_price_cents`, rounded half up to whole cents.

### 3.7. Rental Cycles, Modifier-Adjusted Pricing, and the 13-Month Cap

For a `RENTAL` order that is `ACTIVE`, a `SupplierUser` posts each monthly **rental billing cycle** in turn. Posting a cycle creates it directly in `BILLED` status; rental cycles never exist in any status other than `BILLED`, `PAID`, or `RECOUPED`. The request may optionally carry a `period_start_utc`, which is used to back-bill a correction month at an explicit period start; when it is omitted, the cycle's `period_start_utc` defaults to the order's `ordered_at_utc` advanced by one month for each prior cycle (that is, `ordered_at_utc` plus `cycle_index − 1` months). In either case the cycle's `period_end_utc` is its `period_start_utc` plus one month, treated as an exclusive upper bound. Each new cycle is assigned a `cycle_index` equal to the current maximum `cycle_index` on the order plus one, starting at 1 for the first cycle.

Three preconditions guard cycle posting, and the first two are evaluated in an order that departs from the usual generic-state-first rule. The cap check is evaluated first: if the order's `cap_reached` flag is true, the post is rejected with `ERR_RENTAL_CAP_REACHED`. This ordering ensures that an order which has already converted to purchase because it hit the cap returns the specific cap error rather than a generic state error. Only if the cap has not been reached does the generic state check apply: the order must be `ACTIVE`, and a post against an order that is still `DRAFT`, `DELIVERED`, `CLOSED`, or `CANCELLED` is rejected with `ERR_INVALID_STATE`. Third, the new cycle's period must not overlap any existing cycle on the order; the period is half-open, so a new period whose start equals a prior period's end is allowed, but any true overlap is rejected with `ERR_CYCLE_OVERLAP`.

When a cycle posts successfully, the system creates one claim line of type `RENTAL_MONTH` for that month, sets the cycle's `billed_amount_cents` to the computed amount, and recomputes the order's `rental_months_billed` and `total_allowed_cents`. The count `rental_months_billed` is the number of the order's cycles in `BILLED` or `PAID` status.

The **modifier-adjusted monthly amount** billed on each cycle is computed from the item's `monthly_rental_cents` as the base, the order's `modifier`, the item's `requires_cmn` flag, and the item's `billing_category`. A coverage percentage is selected first: if the modifier is `KX`, coverage is 100 percent; otherwise, if the item requires a certificate of medical necessity, coverage is capped at 80 percent; otherwise coverage is 100 percent. The raw amount is the base multiplied by the coverage percentage and divided by 100, which may be fractional. For items in the `OXYGEN` billing category, the raw amount is then clamped into a band: if it falls below the oxygen floor of 5000 cents it is raised to 5000 cents, and if it exceeds the oxygen ceiling of 20000 cents it is lowered to 20000 cents; for all non-oxygen categories no clamp is applied. The clamped (or unclamped) amount is then rounded half up to whole cents to yield the month's allowed amount.

The **capped rental** discipline bills these monthly amounts in `cycle_index` order, one month at a time at the modifier-adjusted rate in effect for that cycle; the realized rental total is the sum over the cycles actually posted. The cap is 13 months. After each posting, the system recomputes the cap status: an order is considered to have reached the cap when its `billing_category` is `CAPPED_RENTAL` and its `rental_months_billed` is at least 13. Concretely, posting the 12th cycle leaves the cap not reached, while posting the 13th cycle reaches it. When the cycle that posts pushes `rental_months_billed` to 13 on a `CAPPED_RENTAL` order, a cascade fires: the cycle posts in `BILLED` status, the order's `rental_months_billed` becomes 13 and `cap_reached` becomes true, and the order advances from `ACTIVE` to the terminal `CONVERTED_TO_PURCHASE` status. The equipment is then beneficiary-owned, and any further attempt to post a rental cycle is rejected with `ERR_RENTAL_CAP_REACHED`.

A `SupplierUser` or `PayerReviewer` may obtain a **provisional rental quote** for an order before any cycle has been billed. This forward-looking quote projects the full capped-rental obligation in one shot as 13 multiplied by the modifier-adjusted monthly amount computed at today's rate, assuming all 13 months will bill at that rate; it deliberately ignores how many cycles have actually been posted and any future modifier change. The quote response reports `provisional_total_cents` (the 13-month projection), `monthly_allowed_cents` (the single-month modifier-adjusted amount), and `cap_months` (the cap of 13). This contrasts with the realized chronological billing, where the actual total is the sum over the months actually posted and therefore differs from the provisional projection whenever fewer than 13 months have been billed.

Rental cycles may be retrieved individually or listed by a `SupplierUser` or `PayerReviewer`, filterable by `order_id` or `status`. A `PayerReviewer` marks a `BILLED` cycle as paid, which requires the cycle to be in `BILLED` status (`ERR_INVALID_STATE` otherwise), moves the cycle to `PAID`, and moves its linked claim line from `POSTED` to `SETTLED`.

### 3.8. Closing an Order

When a `RENTAL` order that is `ACTIVE` reaches the end of its useful life without hitting the cap, a `SupplierUser` closes it, moving it from `ACTIVE` to the terminal `CLOSED` status. Closing requires the order to be `ACTIVE`; a close request against an order in any other status is rejected with `ERR_INVALID_STATE`. Closing has no further ledger effect.

### 3.9. Claim Lines and the Order Ledger

Every billing event posts a **claim line** against the order. A claim line carries the `order_id` it bills against, an optional `rental_cycle_id` (the rental cycle it corresponds to — set for rental lines, null for purchase lines), an optional `audit_id` (set only when an audit recoups the line), a `line_type`, and an `allowed_amount_cents`. The `line_type` is one of `RENTAL_MONTH`, `PURCHASE`, or `RECOUPMENT`; recoupment lines are system-created and carry negative `allowed_amount_cents`. A claim line is created in `POSTED` status and from there moves to `SETTLED` (when its cycle is paid) or to `VOID` (when an audit voids it). Lines in `VOID` status drop out of the order's `total_allowed_cents`. The order's running total is always the sum of `allowed_amount_cents` over the order's claim lines whose status is not `VOID`, with recoupment lines counted as the negatives they are. Claim lines may be retrieved individually or listed by a `SupplierUser` or `PayerReviewer`, filterable by `order_id`, `rental_cycle_id`, `audit_id`, `line_type`, or `status`.

### 3.10. CPAP Resupply

A CPAP order — one whose catalog item has `is_cpap` true — periodically needs replacement supplies. A `SupplierUser` opens a **CPAP resupply order** by supplying the parent `order_id`, a `supply_kind` (one of `MASK`, `TUBING`, `FILTER`, or `HEADGEAR`), and a `quantity` (an integer from 1 to 12 units). The resupply order may only be created against an order whose catalog item has `is_cpap` true; an attempt to open one against a non-CPAP order is rejected with `ERR_NOT_A_CPAP_ORDER`. The resupply is created in `REQUESTED` status, and its `requested_at_utc` is stamped from the clock at request time — this stamp is the anchor for resupply spacing.

A `SupplierUser` then ships or denies the request. Shipping requires the resupply to be in `REQUESTED` status (`ERR_INVALID_STATE` otherwise) and enforces the resupply spacing window. The window is 90 days: the system finds the most recent prior `SHIPPED` resupply of the same `supply_kind` on the same order, taken by latest `requested_at_utc` (and where two share that instant, the earliest `created_at` breaks the tie). If there is no such prior shipped resupply, the request is eligible. Otherwise the gap in whole days — the elapsed duration between the prior shipped resupply's `requested_at_utc` and this resupply's `requested_at_utc`, taking the floor to whole days — must be at least 90; a gap of exactly 90 days is eligible, while a gap of fewer than 90 days is rejected with `ERR_RESUPPLY_TOO_SOON`. A successful ship moves the resupply to the terminal `SHIPPED` status; denial moves a `REQUESTED` resupply to the terminal `DENIED` status. Resupply orders may be retrieved individually or listed by a `SupplierUser` or `PayerReviewer`, filterable by `order_id`, `supply_kind`, or `status`.

### 3.11. Audits and the Recoupment Cascade

The payer's recourse for defective billing is an **audit**. A `PayerReviewer` opens an audit against an order by supplying the `order_id` and a `reason_code`, one of `NO_VALID_CMN`, `NO_PROOF_OF_DELIVERY`, `OVERBILLED_PAST_CAP`, or `NO_PRIOR_AUTH`. The audit opens in `OPEN` status with `recouped_total_cents` and `recouped_cycle_count` both initialized to 0. From `OPEN`, a reviewer either dismisses the audit or upholds it; both require the audit to be `OPEN` (`ERR_INVALID_STATE` otherwise). Dismissing moves the audit to the terminal `DISMISSED` status with no ledger effect.

Upholding an audit runs the recoupment cascade and moves the audit to the terminal `UPHELD` status. Which rental cycles are recouped depends on the reason code. For the default audit basis — reason codes `OVERBILLED_PAST_CAP`, `NO_VALID_CMN`, and `NO_PRIOR_AUTH` — every cycle on the order in `BILLED` or `PAID` status is recouped, because the underlying certification or authorization defect invalidates the whole billing stream, including amounts not yet settled. For the proof-of-delivery basis — reason code `NO_PROOF_OF_DELIVERY` — only cycles in `PAID` status are recouped, since a missing proof of delivery claws back money that actually moved; cycles still in `BILLED` status are not recouped under this basis, so the recouped total for the same set of cycles is generally smaller than under the default basis.

The cascade processes the recouped cycles in ascending `cycle_index` order. For each such cycle, the cycle moves to `RECOUPED`; one system-created claim line of type `RECOUPMENT` is created whose `allowed_amount_cents` is the negation of that cycle's already-rounded `billed_amount_cents` and whose `audit_id` is the upholding audit's `id`; and the cycle's original linked claim line moves to `VOID`. After all cycles are processed, the order's `total_allowed_cents` is recomputed. The audit's `recouped_total_cents` is set to the sum of the per-cycle absolute amounts — each recouped cycle's `billed_amount_cents` rounded half up to whole cents first, then summed (the system rounds per cycle and then sums, never the reverse) — and its `recouped_cycle_count` is set to the number of cycles recouped. The ledger invariant must hold after the cascade completes: the order's `total_allowed_cents` equals the sum of `allowed_amount_cents` over its non-`VOID` claim lines, with no drift. Audits may be retrieved individually — returned with their recoupment totals — or listed by a `PayerReviewer` or `SupplierUser`, filterable by `order_id` or `status`.

## 4. Endpoint Definitions

All endpoints share the response envelope and authentication rules of Section 2. Resource-creation endpoints return HTTP 201; retrievals, listings, and state-transition or update operations return HTTP 200. Request and response bodies are not restated here — reconstruct them from the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/patients` | Register a beneficiary | `PlatformAdmin` |
| GET | `/patients/{id}` | Get a patient | `PlatformAdmin`, `SupplierUser` |
| POST | `/suppliers` | Register a DME supplier | `PlatformAdmin` |
| GET | `/suppliers/{id}` | Get a supplier | `PlatformAdmin`, `SupplierUser` |
| PATCH | `/suppliers/{id}` | Update supplier accreditation flag | `PlatformAdmin` |
| POST | `/hcpcs-items` | Add a HCPCS catalog item | `PlatformAdmin` |
| GET | `/hcpcs-items/{id}` | Get a catalog item | `PlatformAdmin`, `SupplierUser` |
| POST | `/dme-orders` | Create a DME order in DRAFT | `SupplierUser` |
| GET | `/dme-orders/{id}` | Get a DME order with computed ledger fields | `SupplierUser`, `PayerReviewer`, `PlatformAdmin` |
| GET | `/dme-orders` | List DME orders; filterable by patient, supplier, item, status | `SupplierUser`, `PayerReviewer`, `PlatformAdmin` |
| GET | `/dme-orders/{id}/rental-quote` | Provisional forward-looking capped-rental quote | `SupplierUser`, `PayerReviewer` |
| POST | `/dme-orders/{id}/mark-ready` | Move order to READY_FOR_DELIVERY after compliance gates | `SupplierUser` |
| POST | `/dme-orders/{id}/activate-billing` | Move DELIVERED to ACTIVE; PURCHASE orders post their claim line | `SupplierUser` |
| POST | `/dme-orders/{id}/rental-cycles` | Post the next monthly rental cycle | `SupplierUser` |
| POST | `/dme-orders/{id}/close` | Close an ACTIVE order | `SupplierUser` |
| POST | `/dme-orders/{id}/cancel` | Cancel a DRAFT order | `SupplierUser` |
| POST | `/cmns` | Create a draft Certificate of Medical Necessity | `PhysicianUser` |
| GET | `/cmns/{id}` | Get a CMN | `PhysicianUser`, `SupplierUser`, `PayerReviewer` |
| GET | `/cmns` | List CMNs; filter by order, superseded-by, status | `PhysicianUser`, `SupplierUser`, `PayerReviewer` |
| POST | `/cmns/{id}/activate` | Activate a CMN; OCC-guarded on order version | `PhysicianUser` |
| POST | `/cmns/{id}/revoke` | Revoke an ACTIVE CMN | `PhysicianUser` |
| POST | `/prior-authorizations` | Open a prior authorization request | `SupplierUser` |
| GET | `/prior-authorizations/{id}` | Get a prior authorization | `SupplierUser`, `PayerReviewer` |
| GET | `/prior-authorizations` | List prior authorizations; filter by order, status | `SupplierUser`, `PayerReviewer` |
| POST | `/prior-authorizations/{id}/approve` | Approve a pending prior authorization | `PayerReviewer` |
| POST | `/prior-authorizations/{id}/deny` | Deny a pending prior authorization | `PayerReviewer` |
| POST | `/deliveries` | Schedule a delivery/setup | `SupplierUser` |
| GET | `/deliveries/{id}` | Get a delivery | `SupplierUser`, `PayerReviewer` |
| GET | `/deliveries` | List deliveries; filter by order, status | `SupplierUser`, `PayerReviewer` |
| POST | `/deliveries/{id}/confirm` | Confirm delivery with proof-of-delivery signature | `SupplierUser` |
| POST | `/deliveries/{id}/fail` | Mark a scheduled delivery as failed | `SupplierUser` |
| POST | `/deliveries/{id}/cancel` | Cancel a scheduled delivery | `SupplierUser` |
| GET | `/rental-cycles/{id}` | Get a rental billing cycle | `SupplierUser`, `PayerReviewer` |
| GET | `/rental-cycles` | List rental cycles; filter by order, status | `SupplierUser`, `PayerReviewer` |
| POST | `/rental-cycles/{id}/mark-paid` | Mark a BILLED cycle PAID; linked claim line SETTLED | `PayerReviewer` |
| GET | `/claim-lines/{id}` | Get a claim line | `SupplierUser`, `PayerReviewer` |
| GET | `/claim-lines` | List claim lines; filter by order, cycle, audit, type, status | `SupplierUser`, `PayerReviewer` |
| POST | `/cpap-resupply-orders` | Request a CPAP resupply against a CPAP order | `SupplierUser` |
| GET | `/cpap-resupply-orders/{id}` | Get a CPAP resupply order | `SupplierUser`, `PayerReviewer` |
| GET | `/cpap-resupply-orders` | List CPAP resupply orders; filter by order, kind, status | `SupplierUser`, `PayerReviewer` |
| POST | `/cpap-resupply-orders/{id}/ship` | Ship a requested resupply if outside the 90-day window | `SupplierUser` |
| POST | `/cpap-resupply-orders/{id}/deny` | Deny a requested resupply | `SupplierUser` |
| POST | `/audits` | Open an audit against an order | `PayerReviewer` |
| GET | `/audits/{id}` | Get an audit with recoupment totals | `PayerReviewer`, `SupplierUser` |
| GET | `/audits` | List audits; filter by order, status | `PayerReviewer`, `SupplierUser` |
| POST | `/audits/{id}/uphold` | Uphold an audit; run the recoupment cascade | `PayerReviewer` |
| POST | `/audits/{id}/dismiss` | Dismiss an audit with no ledger effect | `PayerReviewer` |
| POST | `/_clock/set_current_utc` | Set the deterministic system clock | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_VALUE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACQUISITION_TYPE_MISMATCH` | 422 |
| `ERR_CMN_REQUIRED` | 422 |
| `ERR_PRIOR_AUTH_REQUIRED` | 422 |
| `ERR_SUPPLIER_NOT_ACCREDITED` | 422 |
| `ERR_NO_PROOF_OF_DELIVERY` | 422 |
| `ERR_POD_SIGNATURE_REQUIRED` | 422 |
| `ERR_CMN_SIGNED_AFTER_ORDER` | 422 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_RENTAL_CAP_REACHED` | 422 |
| `ERR_CYCLE_OVERLAP` | 422 |
| `ERR_RESUPPLY_TOO_SOON` | 422 |
| `ERR_NOT_A_CPAP_ORDER` | 422 |
