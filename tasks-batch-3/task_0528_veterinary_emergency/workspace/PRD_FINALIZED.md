# Veterinary Emergency API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Veterinary Specialty & Emergency Hospital API — the operational backbone of a multi-department animal hospital that must move a critically ill patient from the front door to discharge without ever losing track of who owns the case, what has been clinically authorized, and what the owner ultimately owes. A typical encounter begins as an emergency-room intake, is triaged by urgency, may be referred to a specialty department such as cardiology or oncology, requires an owner-approved spend ceiling before any billable work occurs, and threads through hospitalization, imaging, surgery, invoicing, and finally a discharge report sent back to the referring veterinarian.

Two pressures shape every rule in this system. The first is clinical safety and continuity: a patient may pass through several attending doctors, occupy scarce ICU cages, and be booked into imaging suites and operating rooms that cannot be double-booked. The second is financial discipline: nothing billable may proceed beyond what an owner has explicitly authorized, and the hospital reconciles an up-front estimate and deposit against the actual finalized charges accrued during the stay. The API therefore behaves as both a workflow orchestrator and a financial ledger, and the two concerns are deliberately intertwined — a clinical action such as performing a procedure is gated by an authorization ceiling, and a financial action such as activating a payment plan changes the clinical case's discharge eligibility.

Because several actors act on the same case in parallel, the system uses immediate consistency and explicit versioning so that a writer who has not observed the latest state of a case cannot silently overwrite a competing decision. The sections below define the global contract (Section 2), the domain workflows and their scattered business rules (Section 3), the endpoint surface (Section 4), and the complete error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When both headers are present but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `TriageNurse`, `ClinicianDVM`, `FinanceCoordinator`, and `Owner`.

Three of these roles carry an opaque operator identity. When `X-User-Role` is `TriageNurse`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ClinicianDVM`: the identifier is opaque, though the server records it as the acting doctor — for example, it becomes the Visit's `attending_dvm_id` when a doctor begins treatment or accepts a referral. Likewise, when `X-User-Role` is `FinanceCoordinator`, `X-User-ID` is an opaque operator identifier that the server does not match against any entity's `id`.

The `Owner` role is entity-backed. When `X-User-Role` is `Owner`, `X-User-ID` is the opaque owning-client identifier stored as `owner_user_id` on a `Patient`; ownership checks on any resource that references a `Patient` (through the Visit's `patient_id`) compare that patient's `owner_user_id` to `X-User-ID`. An `Owner` who attempts to read or act on a case whose patient they do not own is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list responses are sorted by the resource's creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource — Patient, Visit, Referral, Estimate, Authorization, Hospitalization, Procedure, Invoice, and PaymentPlan — carries a system-managed `id` (a UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording first creation, an `updated_at` timestamp (same format) refreshed on every mutation, and an integer `version`. The `version` starts at 1 when the resource is created and increments by exactly 1 on every mutation — including mutations caused by cascades originating on another resource. Whenever a computed field on a resource changes as the result of a cascade, that counts as a mutation of the resource: its `updated_at` is refreshed and its `version` is incremented.

The ReferringVetReport is an exception. It is an append-only discharge artifact generated by the system, and it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field, because it is never mutated after generation.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many resources are addressed through a nested path that names the Visit first and then a child, for example a hospitalization or a procedure belonging to that visit. The system validates the existence of each path-referenced resource left to right, parent before child. If the Visit named in the path does not exist, the request fails with `ERR_NOT_FOUND` before the child is ever considered; only once the parent resolves does the system look up the child, again returning `ERR_NOT_FOUND` if the child is absent. This existence check is a general precondition and is evaluated after authentication and authorization but before any state or business rule.

### 2.6. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: first, authentication — the presence of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`); second, authorization — whether the acting role is permitted for the operation, including an `Owner` acting only on their own patient (`ERR_FORBIDDEN`); third, existence of every path-referenced resource, validated parent-before-child (`ERR_NOT_FOUND`); fourth, malformed-request checks on the body such as a missing required field or a bad enum value (`ERR_INVALID_REQUEST`); fifth, the target resource being in the required state for the requested transition (`ERR_INVALID_STATE`); sixth, cross-entity referential state, such as a referenced estimate being issued or a linked invoice being finalized; seventh, safety guards that block discharge-related transitions while boarding or a procedure is still pending; eighth, temporal booking conflicts on shared resources and cages; ninth, structural constraints such as modality-to-room family matching and cage range; tenth, fiscal ceiling checks; and last, optimistic-concurrency version checks on supersede-create endpoints. Where a rule's own trigger condition is more specific than a general check above it, the specific rule is what applies to that operation, but the general-to-specific ordering above governs which error surfaces when more than one applies.

### 2.7. Monetary Values, Rounding, and Precision

All money in this system is expressed as an integer number of cents; there are no fractional cents and no floating-point currency values in requests or responses. Two rounding operations recur throughout the calculations and must be applied exactly as described where each is invoked. Tax is always computed with the round-half-up method: the fractional cent produced when multiplying a cent amount by the tax rate is rounded to the nearest whole cent, with a tie rounded up. Estimate uplift, deposit amounts, financing fees, and installment amounts are always rounded up to the next whole cent (ceiling). The specific formulas in Section 3 state precisely where each rounding is applied and in what order.

### 2.8. The Authorization Ceiling and Charge Ledger

Every case-scoped resource — Referral, Estimate, Authorization, Hospitalization, Procedure, Invoice, and PaymentPlan — records the id of its parent case in a `visit_id` field, and each such resource also carries a `status` field holding its current lifecycle state as one of the exact uppercase strings enumerated in Section 3. Every Visit maintains two computed money fields that together form the spending ledger for the case: `authorized_ceiling_cents`, the total spend the owner has approved, and `charges_committed_cents`, the running total of finalized charges already posted to the case's invoice. The authorized ceiling is defined as the sum of `approved_ceiling_cents` over every Authorization on the Visit whose status is `ACTIVE`; authorizations in any other status contribute nothing. It is recomputed whenever an authorization becomes active or is voided. The committed-charge total grows as billable work is finalized — when a procedure is performed its price is added, and when a hospitalization is released its accrued board cost is added. The core fiscal invariant of the system is that committed charges may never exceed the authorized ceiling; the specific transitions that enforce this invariant, and the errors they raise, are described in Section 3.

### 2.9. Cascading Consistency Across the Case

A single operation frequently mutates more than one resource, and every such cascade is part of the operation's contract rather than an optional side effect. When an authorization becomes active, for example, it does not merely change its own status — it also consumes the referenced estimate, recomputes the Visit's authorized ceiling, and credits the deposit into the open invoice, each of which is a mutation that bumps the affected resource's `version` and `updated_at`. When a patient is marked deceased, the cascade reaches active hospitalizations and scheduled procedures. Section 3 enumerates each cascade in full. The governing principle is that the system leaves the case in a consistent state after every operation: ceilings, committed totals, invoice balances, and cage and room occupancy always reflect the current set of active child resources, and the server performs these adjustments automatically without requiring a separate client request against each affected resource.

### 2.10. Optimistic Concurrency on Supersede-Create Operations

Two operations in the system are supersede-create operations: they legitimately displace a competing sibling and therefore cannot rely on a state precondition alone to detect a writer acting on stale information. Both guard against this with an optimistic-concurrency check keyed on the parent Visit's `version`.

Issuing an estimate requires the request to carry `expected_visit_version`, the Visit `version` the client last observed. Issuing a newer estimate legitimately supersedes any other issued estimate on the same Visit, so the losing writer cannot be detected by any state check; instead, if `expected_visit_version` does not equal the Visit's current `version` — because another writer has advanced it since the client last read the Visit — the issue is rejected with `ERR_STALE_VERSION` (HTTP 412).

Activating a payment plan likewise requires `expected_visit_version` matching the Visit's current `version`. A newly activated plan settles the invoice and supersedes any competing proposed plan, so again the only deterministic signal for a stale writer is the Visit version: if `expected_visit_version` does not match the current `version`, activation is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field; endpoints that are not supersede-create operations perform no version check.

## 3. Business Logic & Workflows

### 3.1. Registering Patients and Opening a Case

A patient is the animal itself, registered by either a `TriageNurse` or a `FinanceCoordinator`. Registration captures the animal's `name`, its `species` — one of `CANINE`, `FELINE`, or `EXOTIC` — its `weight_kg`, which must be strictly greater than zero, and the `owner_user_id` identifying the owning client. A non-positive `weight_kg` is a malformed request and is rejected with `ERR_INVALID_REQUEST`. The `owner_user_id` is the value that an `Owner` presents as `X-User-ID` when acting on this animal's cases.

A `TriageNurse` opens an emergency-room case by registering a Visit for a patient, supplying the `patient_id` and a free-text `chief_complaint`. A newly opened Visit begins in `REGISTERED` status with its `department` set to `ER`, its `triage_level` still unset, its `authorized_ceiling_cents` and `charges_committed_cents` both at zero, and its `version` at 1. At the same moment, the system creates the single open Invoice that will accumulate this case's charges; there is exactly one invoice per visit, and it starts in `OPEN` status. The Visit's `attending_dvm_id` remains unset until a doctor takes the case. A patient's full case history can be listed by walking from the patient to its visits.

### 3.2. Triage and Early Disposition

Once a case is open, a `TriageNurse` assigns urgency by triaging it, which requires the Visit to be in `REGISTERED` status (otherwise `ERR_INVALID_STATE`) and a `triage_level` drawn from `RED`, `ORANGE`, `YELLOW`, or `GREEN` (any other value is `ERR_INVALID_REQUEST`). Triage moves the Visit from `REGISTERED` to `TRIAGED` and records the chosen `triage_level`. This level is consequential downstream: it fixes the deposit tier applied when an estimate is later issued.

Not every triaged animal stays for care. A `TriageNurse` may record a triaged patient as having left without being seen, moving the Visit from `TRIAGED` to the terminal `LWBS` status. This is permitted only when the Visit is in `TRIAGED` status (`ERR_INVALID_STATE`) and only when no `ACTIVE` Authorization exists on the Visit — if one does, the departure is rejected with `ERR_VISIT_HAS_ACTIVE_AUTH`, because a case with committed authorized spend cannot simply be abandoned as unseen.

### 3.3. Specialty Referral and Multi-Doctor Continuity

Emergency cases often need a specialist. A `ClinicianDVM` creates a Referral against a Visit, naming the `to_department` — one of `CARDIOLOGY`, `ONCOLOGY`, `SURGERY`, or `NEUROLOGY` — the `accepting_dvm_id` of the specialist expected to take the case, and a clinical `reason`. A new referral is `PENDING`.

A specialist resolves a pending referral by accepting or declining it. Accepting requires the Referral to be `PENDING` (`ERR_INVALID_STATE`) and the parent Visit to be in either `TRIAGED` or `IN_TREATMENT` status; a Visit in any other status yields `ERR_VISIT_NOT_OPEN`. Acceptance moves the Referral from `PENDING` to `ACCEPTED` and, in the same operation, transfers the case: the Visit's `department` is set to the referral's `to_department` and the Visit's `attending_dvm_id` is set to the referral's `accepting_dvm_id`. Both the Referral's `version` and the Visit's `version` increment. Declining requires only that the Referral be `PENDING` (`ERR_INVALID_STATE`); it moves the Referral from `PENDING` to `DECLINED`, changes no department, and increments only the Referral's `version`. Both `ACCEPTED` and `DECLINED` are terminal for a referral. The Visit's `attending_dvm_id` — the marker of which doctor currently owns the case — is also set when a doctor begins treatment, so continuity across multiple doctors is expressed through whoever last took the case.

### 3.4. Estimating Cost and Setting the Deposit

Financial planning is owned by the `FinanceCoordinator`, who drafts an Estimate for a Visit by supplying `line_items` — an array of planned charge lines, each with a `code`, a `description`, a `qty` that must be a positive integer, and a `unit_price_cents` that must be a non-negative integer. A new estimate is a `DRAFT`, and its money fields are computed provisionally at creation and then frozen when the estimate is issued.

An estimate carries two bands. The low band is the optimistic quote and the high band is the pessimistic figure that drives the deposit. Both are derived from the raw subtotal, which is the sum, over every line item, of that line's `qty` multiplied by its `unit_price_cents`. The low subtotal is exactly this raw subtotal. The high subtotal takes the raw subtotal, adds a twenty percent clinical-variance uplift (that is, multiplies it by 1.20), and rounds the result up to the next whole cent. Tax is then applied differently to each band. For the low band, `low_cents` is the raw subtotal plus the low tax, where the low tax is computed per line — each line's `qty` multiplied by its `unit_price_cents` multiplied by the tax rate of 0.0725, rounded half-up to a whole cent, and then these per-line taxes summed. For the high band, `high_cents` is the high subtotal plus the high tax, where the high tax is the single uplifted high subtotal multiplied by the tax rate of 0.0725, rounded half-up to a whole cent — that is, tax on the high band is applied once to the summed high number, not line by line.

The deposit is a fraction of the high band determined by the Visit's triage level at the time the estimate is issued. The `deposit_pct` is 0.80 for a `RED` case, 0.60 for `ORANGE`, 0.50 for `YELLOW`, and 0.30 for `GREEN`. The `deposit_cents` is `high_cents` multiplied by `deposit_pct`, rounded up to the next whole cent.

Issuing an estimate is a supersede-create operation performed by the `FinanceCoordinator`. It requires the estimate to be a `DRAFT` (`ERR_INVALID_STATE`) and the Visit to have been triaged — its `triage_level` must be set — otherwise the issue is rejected with `ERR_VISIT_NOT_TRIAGED`. On issue, the estimate moves from `DRAFT` to `ISSUED`, its `low_cents`, `high_cents`, `deposit_pct`, and `deposit_cents` are frozen using the triage level captured at issue time, and any other currently issued estimate on the same Visit is superseded — moved from `ISSUED` to `SUPERSEDED`. Because issuing legitimately supersedes a sibling, the request must carry `expected_visit_version` matching the Visit's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` as described in Section 2.10. An estimate reaches `CONSUMED` only when an authorization referencing it becomes active; both `SUPERSEDED` and `CONSUMED` are terminal.

### 3.5. Owner Authorization: Approving, Declining, and Voiding Spend

No billable treatment proceeds without an owner-approved ceiling. A `FinanceCoordinator` creates an Authorization against a Visit, referencing an `estimate_id` and stating the `approved_ceiling_cents` the owner is willing to sanction. A new authorization is `PENDING`.

The `Owner` acts on their own animal's pending authorization. Approving requires the Authorization to be `PENDING` (`ERR_INVALID_STATE`), the referenced estimate to be in `ISSUED` status (otherwise `ERR_ESTIMATE_NOT_ISSUED`), and the `approved_ceiling_cents` to be at least the referenced estimate's `high_cents` — a ceiling below the estimate's high band is rejected with `ERR_CEILING_BELOW_ESTIMATE`. When these hold, the authorization moves from `PENDING` to `ACTIVE` and a chain of effects follows: the referenced estimate moves from `ISSUED` to `CONSUMED`; the estimate's `deposit_cents` is copied into the authorization's `deposit_paid_cents`; the Visit's `authorized_ceiling_cents` is recomputed as the sum of `approved_ceiling_cents` over all active authorizations; and that deposit is credited into the Visit's open invoice by increasing its `deposit_applied_cents`, after which the invoice's balance is recomputed. The Authorization's `version`, the Estimate's `version`, the Invoice's `version`, and the Visit's `version` all increment.

Declining is the owner's rejection of the proposed spend. It requires the Authorization to be `PENDING` (`ERR_INVALID_STATE`), moves it from `PENDING` to `DECLINED`, and supersedes the referenced estimate — moving it from `ISSUED` to `SUPERSEDED`; both versions increment. Both `DECLINED` and `VOIDED` are terminal for an authorization.

Voiding an active authorization is a compensating action reserved for the `FinanceCoordinator`. It requires the Authorization to be `ACTIVE` (`ERR_INVALID_STATE`) and, critically, may not strand already-committed charges: it is permitted only when the Visit's `charges_committed_cents` is less than or equal to the authorized ceiling that would remain after removing this authorization's `approved_ceiling_cents` — that is, the current `authorized_ceiling_cents` minus this authorization's `approved_ceiling_cents`. If voiding would drop the ceiling below what has already been committed, the request is rejected with `ERR_CEILING_BELOW_COMMITTED`. On a successful void, the authorization moves from `ACTIVE` to `VOIDED`, the Visit's `authorized_ceiling_cents` is recomputed excluding this authorization, this authorization's deposit is removed from the invoice's `deposit_applied_cents`, and the invoice balance is recomputed; the Authorization's, Invoice's, and Visit's `version` fields each increment.

An authorization can be fetched directly by its id at the top level, and the full set for a visit can be listed; authorizations can also be listed and filtered by their `estimate_id`.

### 3.6. Beginning Treatment and Clinical Progress

Clinical treatment begins only after money is authorized. A `ClinicianDVM` begins treatment on a Visit that is in `TRIAGED` status (`ERR_INVALID_STATE`) and that has at least one `ACTIVE` Authorization; a Visit with no active authorization is rejected with `ERR_NO_ACTIVE_AUTH`. Beginning treatment moves the Visit from `TRIAGED` to `IN_TREATMENT` and sets the Visit's `attending_dvm_id` to the acting doctor.

When clinical work is complete, a `ClinicianDVM` marks the case ready for discharge, moving the Visit from `IN_TREATMENT` to `READY_FOR_DISCHARGE`. This requires the Visit to be `IN_TREATMENT` (`ERR_INVALID_STATE`) and that all in-flight work has settled: there must be no `ACTIVE` Hospitalization on the Visit, otherwise `ERR_PATIENT_STILL_BOARDED`, and no `SCHEDULED` Procedure on the Visit, otherwise `ERR_PROCEDURE_PENDING`.

A patient may die during treatment. A `ClinicianDVM` records this from the `IN_TREATMENT` status only (`ERR_INVALID_STATE`), moving the Visit to the terminal `DECEASED` status. Recording death unwinds open commitments: every `ACTIVE` Hospitalization on the Visit is released — which accrues its board cost and posts it to the invoice exactly as a normal release does, then recomputes the invoice's subtotal, tax, and balance — and in parallel every `SCHEDULED` Procedure on the Visit is cancelled, freeing each one's resource-room slot. The Visit's `version` increments.

### 3.7. Hospitalization, Cages, and Per-Diem Board

A `ClinicianDVM` admits a patient to board by creating a Hospitalization on the Visit, specifying the `ward` — `ICU` or `WARD` — a `cage_number`, an `admit_at` instant, and a `planned_discharge_at` instant, where `admit_at` must be strictly earlier than `planned_discharge_at` (otherwise `ERR_INVALID_REQUEST`). A new hospitalization is `ACTIVE` and occupies its cage while active. Two structural constraints apply at admission. A cage is occupied by point-occupancy: a new hospitalization may not reuse a `cage_number` that an `ACTIVE` hospitalization of the same ward already holds, and a collision is rejected with `ERR_CAGE_OCCUPIED`. For the ICU ward, the `cage_number` must fall within 1 through the ICU capacity inclusive; a value outside that range is rejected with `ERR_CAGE_OUT_OF_RANGE`.

Releasing a hospitalization is where board cost accrues. A `ClinicianDVM` releases an `ACTIVE` hospitalization (`ERR_INVALID_STATE`) by supplying a `released_at` instant that must be strictly later than the hospitalization's `admit_at` (otherwise `ERR_INVALID_REQUEST`). The system records `released_at`, computes the nights accrued, and computes the board charge. The nights are the elapsed time from `admit_at` to `released_at` measured in hours, divided by 24 and rounded up to a whole number, but never fewer than one night — that is, the number of accrued nights is the larger of 1 and the ceiling of the hour-span divided by 24. The board charge is the accrued nights multiplied by the per-diem for the ward: an ICU night is 180,000 cents and a general ward night is 60,000 cents. This board charge is appended as a charge line to the Visit's open invoice, the invoice's subtotal, tax, and balance are recomputed, and the Visit's `charges_committed_cents` is increased by the board charge. The hospitalization moves from `ACTIVE` to `RELEASED`, its cage is freed, and the Hospitalization's, Invoice's, and Visit's `version` fields increment. The computed `nights_accrued` and `board_cents` are recorded on the hospitalization.

A hospitalization may instead be cancelled by a `ClinicianDVM` while `ACTIVE` (`ERR_INVALID_STATE`); cancellation posts no board charge, frees the cage, moves the hospitalization from `ACTIVE` to `CANCELLED`, and increments the Hospitalization's and Visit's `version`. Both `RELEASED` and `CANCELLED` are terminal.

### 3.8. Diagnostics and Surgery: Booking, Performing, Cancelling

Imaging and surgery are modeled as Procedures. A `ClinicianDVM` schedules one on a Visit by supplying the `modality` — `IMAGING_CT`, `IMAGING_MRI`, or `SURGERY` — the `resource_room` to book — `CT_SUITE`, `MRI_SUITE`, `OR_1`, or `OR_2` — a `start_at` and an `end_at` instant with `start_at` strictly earlier than `end_at` (otherwise `ERR_INVALID_REQUEST`), and the `price_cents` that this procedure will bill once performed, which must be a non-negative integer. A new procedure is `SCHEDULED` and holds its room slot while scheduled or performed.

Two constraints govern booking. The modality must match the room family: `IMAGING_CT` must book `CT_SUITE`, `IMAGING_MRI` must book `MRI_SUITE`, and `SURGERY` must book `OR_1` or `OR_2`; a mismatch is rejected with `ERR_MODALITY_ROOM_MISMATCH`. The room slot must be free: a new booking may not overlap any existing `SCHEDULED` or `PERFORMED` booking on the same `resource_room`, where overlap is judged on the half-open interval from `start_at` up to but not including `end_at` — two bookings that merely touch at an endpoint do not conflict, but any true overlap is rejected with `ERR_RESOURCE_DOUBLE_BOOKED`.

Performing a procedure is the ceiling-gated billing moment. A `ClinicianDVM` performs a `SCHEDULED` procedure (`ERR_INVALID_STATE`), but only if doing so keeps the case within its authorized spend: the Visit's current `charges_committed_cents` plus this procedure's `price_cents` must be less than or equal to the Visit's `authorized_ceiling_cents`. If performing would push committed charges past the ceiling, it is rejected with `ERR_CEILING_EXCEEDED`. On success, the procedure's charge line is appended to the Visit's open invoice, the invoice subtotal, tax, and balance are recomputed, the Visit's `charges_committed_cents` is increased by `price_cents`, the procedure moves from `SCHEDULED` to `PERFORMED`, and the Procedure's, Invoice's, and Visit's `version` fields increment.

A scheduled procedure may instead be cancelled by a `ClinicianDVM` while `SCHEDULED` (`ERR_INVALID_STATE`); cancellation frees the `resource_room` slot, moves the procedure from `SCHEDULED` to `CANCELLED`, and increments the Procedure's and Visit's `version`. Both `PERFORMED` and `CANCELLED` are terminal.

### 3.9. Invoice Reconciliation, Finalization, and Payment

Each Visit has exactly one Invoice, created open at registration and retrieved as a single-element list for the visit. Its `charge_lines` accumulate in the chronological order charges are posted — each line records the `source_type`, the `source_id`, the `qty`, and the `unit_price_cents` — and every posting recomputes three figures. The `subtotal_cents` is the sum, over all charge lines, of each line's `qty` multiplied by its `unit_price_cents`. The `tax_cents` is computed per line and then summed: for each charge line, take its `qty` multiplied by its `unit_price_cents` multiplied by the tax rate of 0.0725, round that half-up to a whole cent, and add these rounded per-line taxes together. This per-line ordering is authoritative; the alternative of summing the subtotal first and taxing once must not be used, as it can differ by a cent. The `deposit_applied_cents` is the sum of `deposit_paid_cents` over the Visit's `ACTIVE` authorizations. The `balance_due_cents` is the subtotal plus the tax minus the applied deposit, floored at zero so it never goes negative.

A `FinanceCoordinator` finalizes the invoice, which requires it to be `OPEN` (`ERR_INVALID_STATE`) and requires that no `SCHEDULED` Procedure and no `ACTIVE` Hospitalization remain on the Visit — outstanding work of either kind blocks finalization with `ERR_CHARGES_PENDING`. Finalization locks the `charge_lines`, recomputes `tax_cents` per line and `balance_due_cents`, moves the invoice from `OPEN` to `FINALIZED`, and increments the Invoice's and Visit's `version`.

Settlement can happen two ways. A `FinanceCoordinator` records a full payment against a `FINALIZED` invoice (`ERR_INVALID_STATE`) by supplying `amount_cents`; the payment settles the invoice only if `amount_cents` is at least the `balance_due_cents`, and an amount below the balance is rejected with `ERR_PAYMENT_INSUFFICIENT`. A successful full payment moves the invoice from `FINALIZED` to `SETTLED` and increments the Invoice's and Visit's `version`. Alternatively, the invoice reaches `SETTLED` when a payment plan linked to it becomes active, as described next.

### 3.10. Financing: Payment Plans and CareCredit Promotions

When an owner cannot pay in full, a `FinanceCoordinator` proposes a PaymentPlan against a finalized invoice, supplying the `invoice_id`, the `provider` — `CARECREDIT` or `IN_HOUSE` — and the `term_months`, an integer number of monthly installments between 1 and 24 inclusive. A new plan is `PROPOSED`. Its financial schedule is computed at proposal in a strictly pinned order, because each figure depends on the ones before it.

First, the `principal_cents` is copied from the linked invoice's `balance_due_cents` at plan creation. Second, promotional eligibility is determined: `promo_applied` is true if and only if the provider is `CARECREDIT` and the `principal_cents` is at least 100,000 cents and the `term_months` is at most 6; if any of those three conditions fails, no promotion applies. Third, the financing fee is set from that eligibility: when the promotion applies, the `financing_fee_cents` is zero; otherwise the `financing_fee_cents` is the principal multiplied by the monthly rate of 0.0225 multiplied by the number of `term_months`, rounded up to the next whole cent. Fourth, the total to be financed is the principal plus the financing fee. Fifth, the schedule is split into installments: the `installment_cents` charged for each of the first `term_months` minus one installments is the total divided by `term_months`, rounded up to the next whole cent, and the `final_installment_cents` is the remainder — the total minus the per-installment amount multiplied by the number of installments before the last (that is, `term_months` minus one) — so the last installment absorbs any rounding remainder.

Activating a plan is a supersede-create operation performed by the `FinanceCoordinator`. It requires the plan to be `PROPOSED` (`ERR_INVALID_STATE`), the linked invoice to be `FINALIZED` (otherwise `ERR_INVOICE_NOT_FINALIZED`), and no other `ACTIVE` payment plan already linking the same invoice (otherwise `ERR_PLAN_ALREADY_ACTIVE`). Because a newly active plan settles the invoice and supersedes any competing proposed plan, activation must carry `expected_visit_version` matching the Visit's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per Section 2.10. On activation, the plan moves from `PROPOSED` to `ACTIVE`, the linked invoice moves from `FINALIZED` to `SETTLED`, and the Invoice's and Visit's `version` increment along with the PaymentPlan's own `version`. A proposed plan may instead be cancelled by a `FinanceCoordinator` while `PROPOSED` (`ERR_INVALID_STATE`), moving it to the terminal `CANCELLED` status. A payment plan can be fetched directly by its id at the top level, listed for a visit, or listed and filtered by `invoice_id`.

### 3.11. Discharge and the Referring-Veterinarian Report

Discharge is the clinical and financial closing of the case, performed by a `ClinicianDVM`. It requires the Visit to be in `READY_FOR_DISCHARGE` status (`ERR_INVALID_STATE`) and the Visit's invoice to be `SETTLED`; an unsettled invoice blocks discharge with `ERR_INVOICE_NOT_SETTLED`. Discharge moves the Visit from `READY_FOR_DISCHARGE` to the terminal `DISCHARGED` status and triggers two cascading effects. First, if the invoice is not already finalized it is finalized now — its `charge_lines` are locked and its tax recomputed per line. Second, a ReferringVetReport is generated as the discharge artifact. The report is created against the Visit and records the `referring_dvm_email` recipient and a `summary` narrative; it also snapshots the case at report time — its `procedures_performed` is the list of `PERFORMED` procedure ids on the Visit, and its `total_billed_cents` is the Visit invoice's `subtotal_cents` plus `tax_cents` at generation. The Visit's `version` increments. Because the report is append-only, it carries only `id` and `created_at` and is never versioned. Reports for a visit can be listed.

### 3.12. Test-Driving the Logical Clock

Because board accrual and booking windows depend on time, the system runs on a logical clock rather than wall-clock time. Its default before any adjustment is a fixed instant, and an operator — a `TriageNurse`, `ClinicianDVM`, or `FinanceCoordinator` — may advance or set it by supplying a `to_iso8601` instant. This capability exists to make time-dependent behavior deterministic during evaluation; the supplied instant becomes the current logical time used for subsequent calculations.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions and list or fetch reads — return `200 OK`. Request bodies, response payloads, and side effects for each endpoint are defined by the workflow narratives in Section 3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Register a patient (animal) | TriageNurse, FinanceCoordinator |
| GET | `/patients/{id}` | Get a patient | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| GET | `/patients/{id}/visits` | List visits for a patient | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits` | Register an ER visit for a patient | TriageNurse |
| GET | `/visits/{id}` | Get a visit with computed ceiling/committed fields | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/triage` | Assign triage level | TriageNurse |
| POST | `/visits/{id}/begin-treatment` | Begin clinical treatment | ClinicianDVM |
| POST | `/visits/{id}/ready-for-discharge` | Mark case ready for discharge | ClinicianDVM |
| POST | `/visits/{id}/discharge` | Discharge the patient | ClinicianDVM |
| POST | `/visits/{id}/mark-deceased` | Record patient death | ClinicianDVM |
| POST | `/visits/{id}/mark-lwbs` | Mark left-without-being-seen | TriageNurse |
| POST | `/visits/{id}/referrals` | Create a referral to a specialty department | ClinicianDVM |
| GET | `/visits/{id}/referrals` | List referrals for a visit | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/referrals/{referralId}/accept` | Accept a referral | ClinicianDVM |
| POST | `/visits/{id}/referrals/{referralId}/decline` | Decline a referral | ClinicianDVM |
| POST | `/visits/{id}/estimates` | Create a draft estimate | FinanceCoordinator |
| GET | `/visits/{id}/estimates` | List estimates for a visit | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| GET | `/visits/{id}/estimates/{estimateId}` | Get an estimate | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/estimates/{estimateId}/issue` | Issue an estimate (freezes amounts) | FinanceCoordinator |
| POST | `/visits/{id}/authorizations` | Create a pending authorization | FinanceCoordinator |
| GET | `/visits/{id}/authorizations` | List authorizations for a visit | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| GET | `/authorizations/{authorizationId}` | Get a single authorization | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| GET | `/authorizations` | List authorizations, filterable by estimate_id | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/authorizations/{authorizationId}/approve` | Owner approves an authorization | Owner |
| POST | `/visits/{id}/authorizations/{authorizationId}/decline` | Owner declines an authorization | Owner |
| POST | `/visits/{id}/authorizations/{authorizationId}/void` | Void an active authorization | FinanceCoordinator |
| POST | `/visits/{id}/hospitalizations` | Admit patient to a board and cage | ClinicianDVM |
| GET | `/visits/{id}/hospitalizations` | List hospitalizations for a visit | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/hospitalizations/{hospitalizationId}/release` | Release from board; accrue per-diem | ClinicianDVM |
| POST | `/visits/{id}/hospitalizations/{hospitalizationId}/cancel` | Cancel an admission | ClinicianDVM |
| POST | `/visits/{id}/procedures` | Schedule a diagnostics/surgery procedure | ClinicianDVM |
| GET | `/visits/{id}/procedures` | List procedures for a visit | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/procedures/{procedureId}/perform` | Mark a procedure performed | ClinicianDVM |
| POST | `/visits/{id}/procedures/{procedureId}/cancel` | Cancel a scheduled procedure | ClinicianDVM |
| GET | `/visits/{id}/invoice` | Get the Visit's invoice as a list | TriageNurse, ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/visits/{id}/invoice/finalize` | Finalize the invoice | FinanceCoordinator |
| POST | `/visits/{id}/invoice/pay` | Record a full payment; settle the invoice | FinanceCoordinator |
| POST | `/visits/{id}/payment-plans` | Propose a payment plan | FinanceCoordinator |
| GET | `/visits/{id}/payment-plans` | List payment plans for a visit | FinanceCoordinator, Owner |
| GET | `/payment-plans/{paymentPlanId}` | Get a single payment plan | FinanceCoordinator, Owner |
| GET | `/payment-plans` | List payment plans, filterable by invoice_id | FinanceCoordinator, Owner |
| POST | `/visits/{id}/payment-plans/{paymentPlanId}/activate` | Activate a proposed plan; settle the invoice | FinanceCoordinator |
| POST | `/visits/{id}/payment-plans/{paymentPlanId}/cancel` | Cancel a proposed plan | FinanceCoordinator |
| GET | `/visits/{id}/referring-vet-reports` | List referring-DVM reports for a visit | ClinicianDVM, FinanceCoordinator, Owner |
| POST | `/_clock/set_current_utc` | Set the logical clock | TriageNurse, ClinicianDVM, FinanceCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VISIT_NOT_TRIAGED` | 409 |
| `ERR_VISIT_NOT_OPEN` | 409 |
| `ERR_NO_ACTIVE_AUTH` | 409 |
| `ERR_VISIT_HAS_ACTIVE_AUTH` | 409 |
| `ERR_ESTIMATE_NOT_ISSUED` | 409 |
| `ERR_CEILING_BELOW_ESTIMATE` | 409 |
| `ERR_CEILING_EXCEEDED` | 409 |
| `ERR_CEILING_BELOW_COMMITTED` | 409 |
| `ERR_PATIENT_STILL_BOARDED` | 409 |
| `ERR_PROCEDURE_PENDING` | 409 |
| `ERR_CHARGES_PENDING` | 409 |
| `ERR_RESOURCE_DOUBLE_BOOKED` | 409 |
| `ERR_CAGE_OCCUPIED` | 409 |
| `ERR_MODALITY_ROOM_MISMATCH` | 422 |
| `ERR_CAGE_OUT_OF_RANGE` | 422 |
| `ERR_INVOICE_NOT_SETTLED` | 409 |
| `ERR_INVOICE_NOT_FINALIZED` | 409 |
| `ERR_PLAN_ALREADY_ACTIVE` | 409 |
| `ERR_PAYMENT_INSUFFICIENT` | 402 |
| `ERR_STALE_VERSION` | 412 |
