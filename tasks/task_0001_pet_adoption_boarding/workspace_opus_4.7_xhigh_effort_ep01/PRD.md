# Pet Adoption & Boarding Platform API — Product Requirements Document

## 1. Introduction

Animal shelters routinely juggle two parallel business flows that touch the same physical animal inventory: long-term adoption placement and short-term paid boarding. When these flows are managed in disconnected spreadsheets, the result is double-booked animals, adoptions finalised against expired rabies vaccines, and boarding invoices that drift from the quoted price. The Pet Adoption & Boarding Platform API consolidates both flows behind a single versioned resource graph so that shelter staff, adopters, inspectors and finance officers observe the same authoritative state.

The platform enforces an approval-chain model for adoption (reviewer → approver, with segregation of duties), a coordinator-led model for boarding, and a finance-officer-owned settlement workflow. It also enforces a single species-specific vaccination-compliance contract that gates every operation where an animal leaves the shelter or changes legal status. Derived fields — shelter slot counts, home-visit validity windows, pinned fees — are computed server-side and never accepted from the client, so that optimistic-concurrency-control (OCC) becomes the only acceptable path to mutate shared state.

## 2. Global Specifications & System-Wide Principles

### 2.1. Authentication, Identity, and Role-Based Access Control

Every request carries two headers that identify the calling principal. `X-User-ID` names the individual actor (used for segregation-of-duties checks), while `X-User-Role` declares the role under which the call is made. Missing, blank, or otherwise unparseable header values yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the header is well-formed but the role is not entitled to the requested endpoint, the platform responds with `ERR_INSUFFICIENT_PERMISSIONS`.

The nine roles understood by the system are `ShelterAdmin`, `Veterinarian`, `AdoptionReviewer`, `AdoptionApprover`, `HomeVisitInspector`, `BoardingCoordinator`, `FinanceOfficer`, `Adopter`, and `Any`. The `Any` value is a pseudo-role applied only to read-only list and get endpoints — authenticated callers of any valid role may invoke them. Sensitive transitions are guarded by exclusive ownership: only `ShelterAdmin` creates shelters and animal records; only `AdoptionReviewer` invokes begin-review and request-home-visit; only `AdoptionApprover` may approve, reject or finalize an application; only `HomeVisitInspector` submits a home visit; only `BoardingCoordinator` checks animals in and out of boarding; only `FinanceOfficer` captures payment, refunds a settlement, or marks a boarding reservation `SETTLED`. Certain operations are shared — `Veterinarian` and `ShelterAdmin` both record vaccinations; `Adopter` and `BoardingCoordinator` both create boarding reservations; `Adopter` and `HomeVisitInspector` both cancel a scheduled home visit.

### 2.2. API Response Envelope

Every response — success or error — is wrapped in a uniform envelope. A canonical success response for a single resource looks like:

```json
{
  "meta": {
    "api_request_id": "req_petpaw_01HM9A8V2RK3",
    "api_request_timestamp": "2026-03-14T09:42:17.284Z"
  },
  "response_type": "object",
  "data": {
    "id": "a2d7c51e-9b1a-4f60-8c23-712f6e7ac945",
    "name": "Biscuit",
    "species": "DOG",
    "status": "AVAILABLE",
    "version": 3,
    "created_at": "2026-02-01T08:00:00.000Z",
    "updated_at": "2026-03-14T09:42:17.284Z"
  }
}
```

A list response replaces `response_type` with `"array"` and populates pagination fields on `meta`:

```json
{
  "meta": {
    "api_request_id": "req_petpaw_01HM9A8V2RK4",
    "api_request_timestamp": "2026-03-14T09:42:18.019Z",
    "limit": 50,
    "offset": 0,
    "total_count": 137,
    "has_more": true
  },
  "response_type": "array",
  "data": [ ]
}
```

An error response is structurally identical at the envelope level, with a fixed error payload:

```json
{
  "meta": {
    "api_request_id": "req_petpaw_01HM9A8V2RK5",
    "api_request_timestamp": "2026-03-14T09:42:19.551Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "ERR_ANIMAL_ALREADY_RESERVED",
    "message": "Another approved adoption application already holds this animal."
  }
}
```

Field semantics are fixed. `api_request_id` is a server-generated token, unique per request, suitable for log correlation; clients must not fabricate it. `api_request_timestamp` is always ISO 8601 UTC with exactly three fractional-second digits. `response_type` is one of the three enumerated literals `"object"`, `"array"`, or `"error"`. `data` carries the business payload: an object for single-resource results, an array for list results, and the `{ error_id, message }` pair for errors. The pagination fields (`limit`, `offset`, `total_count`, `has_more`) appear in `meta` only for list endpoints.

### 2.3. Pagination and Sort Order

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 50, with a minimum of 1 and a maximum of 200; values outside this range are rejected as `ERR_INVALID_REQUEST`. `offset` defaults to 0. Results are returned sorted by `created_at` ascending unless otherwise noted. The envelope reports the effective `limit` and `offset`, the total number of rows matching the filter as `total_count`, and the boolean `has_more` signalling whether further pages exist.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

All resources carry a `id` in UUID form. Where `common_fields` apply — `Shelter`, `Animal`, `Adopter`, `HomeVisit`, `AdoptionApplication`, `BoardingReservation`, `FeeSettlement` — each resource additionally carries `created_at`, `updated_at`, and a monotonically increasing `version` integer that starts at 1 and increments on every mutation. `VaccinationRecord` and `ComplianceIncident` are append-only audit records; they expose `created_at` but do not maintain `updated_at` or `version`, because they are never modified after insertion.

Timestamps are always ISO 8601 UTC with three fractional-second digits. On every mutation the server refreshes `updated_at` on the affected resource and increments `version` by exactly one. Cascading mutations (e.g., Animal transitioning under approval) bump the animal's `version` too, even if the triggering request targeted a different resource.

Optimistic concurrency control operates on the `version` field. `PATCH /shelters/{sid}/animals/{aid}` accepts an optional `version` in the request body; when supplied, the platform compares it to the live row and returns `ERR_VERSION_CONFLICT` if the two diverge. Omitting `version` skips the check — a deliberate escape hatch for admin recovery, not a routine pattern. Finalization of an adoption uses a stronger, pinned variant: `pinned_animal_version` was captured at approval, and at finalize time it must still equal the live `Animal.version`, otherwise `ERR_STALE_PINNED_REFERENCE` is raised.

### 2.5. Nested-Path Resolution

Path parameters are validated left-to-right. A request to `/shelters/{sid}/animals/{aid}/vaccinations` first verifies the shelter exists (else `ERR_SHELTER_NOT_FOUND`), then the animal (else `ERR_ANIMAL_NOT_FOUND`), then that the animal belongs to the shelter. Deeper resources follow the same pattern: `ERR_ADOPTER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_HOME_VISIT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, and `ERR_SETTLEMENT_NOT_FOUND` are reserved for their respective segments. Existence errors always precede body-level or business errors.

### 2.6. Monetary Precision and Rounding

All monetary quantities — `adoption_fee_base`, `boarding_rate_per_night`, `adoption_fee_override`, `pinned_fee`, `quoted_total`, `final_total`, `amount` — are stored and transmitted as integer cents. Multiplicative operations (senior discount, special-care multiplier, peak surcharge) are evaluated in exact arithmetic and rounded at the final step using the round-half-up convention, to a precision of zero fractional cents. No intermediate rounding is performed before the final composite figure is determined.

### 2.7. Validation Ordering (Which Check Fires First)

When a single request would fail multiple checks, the platform evaluates them in a fixed priority order so that the `error_id` returned is deterministic. The order is: (1) header validation — missing `X-User-ID` or `X-User-Role` surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role entitlement — `ERR_INSUFFICIENT_PERMISSIONS`; (3) path-parameter existence from left to right — the four-hundred-four family; (4) request body well-formedness — `ERR_INVALID_REQUEST`, plus the specialised `ERR_INVALID_SCORE` for `safety_score` outside the `[0..100]` band; (5) optimistic-concurrency version match on `PATCH` — `ERR_VERSION_CONFLICT`; (6) target-resource state suitability — `ERR_INVALID_STATE`; (7) business-compliance rules (segregation of duties, home visit validity, vaccination compliance); (8) business constraints (animal availability, boardability, adopter disqualification); (9) capacity — `ERR_SHELTER_AT_CAPACITY`; and (10) fiscal rules (amount match, duplicate settlement).

Within level 7, the three business-compliance checks on `POST /adoption-applications/{id}/approve` are evaluated as: segregation of duties first (`ERR_SEGREGATION_OF_DUTIES`), then home-visit requirement (`ERR_HOME_VISIT_REQUIRED`), then vaccination compliance (`ERR_VACCINATION_NON_COMPLIANT`). Within level 8, animal-availability (`ERR_ANIMAL_UNAVAILABLE` / `ERR_ANIMAL_ALREADY_RESERVED`) is evaluated before adopter-disqualification (`ERR_ADOPTER_DISQUALIFIED`) on approve. On boarding reservation create, `ERR_ANIMAL_NOT_BOARDABLE` is evaluated before the capacity check `ERR_SHELTER_AT_CAPACITY`, so a reservation for an already-adopted animal surfaces its correct rejection even at a full shelter.

### 2.8. Concurrency Guarantees

The platform serialises four specific races. When two approvers simultaneously call approve for different applications targeting the same animal, the first-writer-wins on the `AVAILABLE → HELD` transition; the loser receives `ERR_ANIMAL_ALREADY_RESERVED` with HTTP 409. When two boarding reservations race for the final slot of a shelter (i.e., `available_slots == 1`), the atomic decrement of `available_slots` under row lock lets exactly one caller succeed; the loser receives `ERR_SHELTER_AT_CAPACITY`. When capture and refund are invoked simultaneously on the same `FeeSettlement`, exactly one succeeds; the loser receives `ERR_INVALID_STATE`. When adoption finalization races a concurrent animal edit (for example, a newly-recorded vaccine that expires the compliance set), finalize either succeeds against a still-valid state or rejects with `ERR_STALE_PINNED_REFERENCE` (when `Animal.version` no longer matches `pinned_animal_version`) or `ERR_VACCINATION_NON_COMPLIANT` (when the `Animal.version` is unchanged but the compliance set is no longer satisfied). Finally, a routine `PATCH` with a stale `version` is rejected with `ERR_VERSION_CONFLICT`.

### 2.9. Audit Trail

`VaccinationRecord` is append-only — it is never updated and never deleted. The `ComplianceIncident` log is likewise append-only; a new row is created whenever vaccination compliance blocks an operation, with `incident_type` drawn from `VACCINE_EXPIRED`, `VACCINE_MISSING`, `ADOPTION_BLOCKED`, or `BOARDING_BLOCKED`, the `triggered_by` field naming the endpoint or system event, the `detail` string carrying a human-readable explanation, and `created_at` set to the insertion moment.

## 3. Business Logic & Workflows

### 3.1. Shelter Setup, Animal Intake, and Vaccination Bookkeeping

A `ShelterAdmin` opens operations by creating a shelter with a request carrying `name`, `boarding_capacity`, `adoption_fee_base` and `boarding_rate_per_night`. The new shelter is materialised with `status` set to `OPEN`; its `reserved_slots` counter starts at zero, and `available_slots` — always computed as `boarding_capacity` minus `reserved_slots`, floored at zero — therefore equals the declared capacity. A shelter may later be placed in `SUSPENDED` status, at which point creation of new reservations must halt.

Animal intake is similarly an admin privilege. A `POST /shelters/{sid}/animals` call carries `name`, `species` (one of `DOG`, `CAT`, `RABBIT`, `OTHER`), `age_months`, optionally a list of `temperament_tags` such as `KID_FRIENDLY`, `HIGH_ENERGY` or `NEEDS_YARD` (defaulting to an empty array), optionally an `adoption_fee_override` expressed in cents that supersedes the shelter's base, and optionally a `special_care_level` of `NONE`, `MEDICAL`, or `BEHAVIORAL`. The platform stamps `intake_date` at creation and initialises `status` to `AVAILABLE`. The inherited `shelter_id` is resolved from the path and made visible on the resource. Admins later adjust intake metadata via `PATCH /shelters/{sid}/animals/{aid}` supplying any of `name`, `temperament_tags`, `adoption_fee_override`, `special_care_level`, alongside the current `version` for the OCC check.

Vaccinations are logged through `POST /shelters/{sid}/animals/{aid}/vaccinations`, available to both `ShelterAdmin` and `Veterinarian`. Each record captures `vaccine_type` (one of `RABIES`, `DISTEMPER`, `PARVO`, `BORDETELLA`, `FELV`), `administered_date`, `expires_date`, and the `lot_number` of the dose. Because records are never edited, the latest record per `vaccine_type` for a given `animal_id` is the authoritative statement of coverage. `GET /shelters/{sid}/animals/{aid}/vaccinations` lists them with optional `vaccine_type` filter, and `GET /shelters/{sid}/animals/{aid}/compliance` returns the derived `{status, missing, expired}` triple used by downstream approval workflows.

### 3.2. The Vaccination Compliance Contract

Compliance is evaluated by set coverage with recency. Each species implies a required vaccine set: a `DOG` must be current on `RABIES`, `DISTEMPER`, `PARVO`, and `BORDETELLA`; a `CAT` on `RABIES`, `DISTEMPER`, and `FELV`; a `RABBIT` on `RABIES`; `OTHER` species on `RABIES` alone. For each required `vaccine_type`, the platform locates the record with the maximum `administered_date` for the animal; if none exists, the animal is non-compliant with reason `VACCINE_MISSING`, and if one does exist but its `expires_date` is less than or equal to the current instant, the reason is `VACCINE_EXPIRED`. The boundary is strict — an `expires_date` of exactly now is already expired. When any of `POST /adoption-applications/{id}/approve`, `POST /adoption-applications/{id}/finalize`, `POST /shelters/{sid}/boarding-reservations`, or `POST /shelters/{sid}/boarding-reservations/{rid}/check-in` discovers non-compliance, it responds with `ERR_VACCINATION_NON_COMPLIANT` and writes a `ComplianceIncident` naming the triggering endpoint.

### 3.3. Adopter Registration and Home Visit Lifecycle

An adopter self-registers — or is registered by a `ShelterAdmin` on the adopter's behalf — through `POST /adopters` with `full_name`, `household_size`, and `has_yard`. The resource is created with `home_visit_status` set to `PENDING` and `disqualified` initialised to `false`. Retrieval is done through `GET /adopters/{id}`, and the response surfaces the derived `home_visit_expires_at` whenever a `PASSED` visit is on file.

Home visits follow their own state machine anchored on the adopter. An `AdoptionReviewer` schedules a visit through `POST /adopters/{id}/home-visits` with `scheduled_for` and the `inspector_id` of the `HomeVisitInspector` who will attend. The new visit enters state `SCHEDULED`. The inspector later submits the assessment via `POST /adopters/{id}/home-visits/{hvId}/submit`, providing `safety_score` in the `[0..100]` band (outside the band yields `ERR_INVALID_SCORE`) and optionally `yard_verified`. The platform rejects submission from anyone other than the assigned inspector with `ERR_INSUFFICIENT_PERMISSIONS`. Upon acceptance, `completed_at` is stamped with the server clock and the visit moves to `SUBMITTED`, then transitions automatically to `PASSED` when the score is at least 70 or to `FAILED` otherwise. A pass sets `Adopter.home_visit_status` to `PASSED` and writes `home_visit_expires_at` at 180 days from the completion moment; a failure cascades: any of the adopter's applications sitting in `HOME_VISIT_REQUIRED` are force-rejected with `ERR_HOME_VISIT_FAILED`. A visit that has not yet been submitted may be cancelled by either the adopter or the inspector via `POST /adopters/{id}/home-visits/{hvId}/cancel`, moving it to `CANCELLED`. Listing is available through `GET /adopters/{id}/home-visits`, which `AdoptionApprover`s consult alongside reviewers.

A passed home visit has a finite useful life. When the current instant is still earlier than the `completed_at` plus that 180-day window, `home_visit_status` reads `PASSED`; once the window closes, it reads `EXPIRED` and, for approval purposes, is treated identically to `PENDING` — a fresh home visit is mandatory.

### 3.4. Adoption Application Journey

A prospective adopter submits their interest through `POST /adoption-applications` supplying `adopter_id`, the target `animal_id`, and optional `review_notes`. The platform resolves the `shelter_id` from the animal, initialises `status` to `SUBMITTED`, and rejects the submission if the animal is already subject to an `APPROVED` or `FINALIZED` application (with `ERR_ANIMAL_ALREADY_RESERVED`), if the animal is otherwise unavailable (with `ERR_ANIMAL_UNAVAILABLE`), or if the adopter's `disqualified` flag is set (with `ERR_ADOPTER_DISQUALIFIED`). The application is retrievable through `GET /adoption-applications/{id}` and enumerable through `GET /adoption-applications` (filterable by `status`, `adopter_id`, or `animal_id`).

Review is an `AdoptionReviewer` activity. Calling `POST /adoption-applications/{id}/begin-review` requires the application to be in `SUBMITTED` (else `ERR_INVALID_STATE`) and the adopter to still hold `disqualified == false`; the platform records the reviewer's `X-User-ID` as the `reviewer_user_id` to be consulted later by the segregation-of-duties check. If the reviewer determines a home visit is required — either because the adopter has no `PASSED` visit on file or the existing one is `EXPIRED` — they call `POST /adoption-applications/{id}/request-home-visit`, which moves the application to `HOME_VISIT_REQUIRED`; an actual visit, if one is not already active, is then arranged through the home-visit endpoint described above.

Approval is reserved for the `AdoptionApprover` role, and is subject to five enumerated preconditions evaluated in the priority order from §2.7. First, the approver's `X-User-ID` must differ from the recorded `reviewer_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). Second, `Adopter.home_visit_status` must be `PASSED` and unexpired (else `ERR_HOME_VISIT_REQUIRED`). Third, vaccination compliance must currently hold (else `ERR_VACCINATION_NON_COMPLIANT`). Fourth, the animal must be in `AVAILABLE` or already `HELD` for this application (else `ERR_ANIMAL_UNAVAILABLE`). Fifth, no other application on this animal may already be in `APPROVED` or `FINALIZED` (else `ERR_ANIMAL_ALREADY_RESERVED`). When all five pass, `POST /adoption-applications/{id}/approve` writes `status = APPROVED`, transitions the animal to `HELD`, pins `pinned_animal_version` to the live `Animal.version` at that moment, snapshots the current compliance set into `pinned_vaccination_snapshot`, computes the adoption fee and locks it into `pinned_fee` — and, crucially, cascades every sibling application on the same animal (those still in `SUBMITTED`, `UNDER_REVIEW`, or `HOME_VISIT_REQUIRED`) to `REJECTED` with `ERR_ANIMAL_ALREADY_RESERVED`.

Rejection uses `POST /adoption-applications/{id}/reject`, optionally including refreshed `review_notes`. It is permitted from any of `SUBMITTED`, `UNDER_REVIEW`, or `HOME_VISIT_REQUIRED`, and is again subject to segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) so that the reviewer cannot unilaterally conclude their own file. Should the rejected application have been solely responsible for holding the animal, the animal falls back to `AVAILABLE`. Adopters themselves may abandon a submission through `POST /adoption-applications/{id}/withdraw` — permitted from `SUBMITTED`, `UNDER_REVIEW`, `HOME_VISIT_REQUIRED`, or even `APPROVED`, but never after `FINALIZED` (`ERR_INVALID_STATE`), and only when the `X-User-ID` matches the applicant (`ERR_INSUFFICIENT_PERMISSIONS`). Withdrawal releases any exclusive animal hold and fails any `PENDING` adoption settlement for the application.

Finalization is the last official act. `POST /adoption-applications/{id}/finalize` requires that a `COMPLETED` `FeeSettlement` exists for the `(ADOPTION, application_id)` subject pair (else `ERR_FEE_NOT_SETTLED`), that the live `Animal.version` still equals `pinned_animal_version` (else `ERR_STALE_PINNED_REFERENCE`), and that vaccination compliance still holds (else `ERR_VACCINATION_NON_COMPLIANT`). On success it sets `Animal.status = ADOPTED` and cascades any `RESERVED` `BoardingReservation` for that animal to `CANCELLED` with `ERR_ANIMAL_ADOPTED`, releasing their slots. Because approval mutates `Animal` (and therefore bumps its `version`), every subsequent animal edit is a potential invalidator of the pin: a `HIGH`-risk vaccine backdating that expires coverage, for instance, simultaneously changes `Animal.version` and can fail the pin check. This coupling is the intended serialization point between animal edits and finalization.

### 3.5. Adoption Fee Calculation (Dual-Variant)

The adoption fee is derived from the animal under the following rule: if `adoption_fee_override` is set on the animal, that value is the fee; otherwise the fee is the parent shelter's `adoption_fee_base`. If the animal's `age_months` is at least 96 — an eight-year threshold encoded as `SENIOR_AGE_MONTHS` — the fee is halved under the senior discount (`SENIOR_DISCOUNT` of 0.5), rounded half up to whole cents. Approval pins this figure into `pinned_fee`, insulating the settlement from later animal edits. Capture re-evaluates the fee from the current animal state and demands exact equality with the pinned figure; any drift is rejected as `ERR_AMOUNT_MISMATCH`.

### 3.6. Boarding Reservation, Occupancy, and Quoting

Boarding is booked through `POST /shelters/{sid}/boarding-reservations`, with `animal_id`, `owner_id` (the adopter acting as owner), `check_in_date`, and `check_out_date`. The animal must belong to the target shelter and must not currently be in `ADOPTED` or `RETIRED` status (else `ERR_ANIMAL_NOT_BOARDABLE`); vaccination compliance must hold; the shelter must have a slot free. When a reservation is admitted, the platform writes `status = RESERVED`, atomically increments the shelter's `reserved_slots`, and snapshots a `quoted_total` on the resource.

The quote computes `nights` as the whole-day difference `check_out_date − check_in_date`, with the check-out moment treated as exclusive; a request that resolves to fewer than one night is rejected as `ERR_INVALID_REQUEST`. The baseline is the shelter's `boarding_rate_per_night` multiplied by `nights`. A special-care multiplier adjusts the baseline — 1.5x when `special_care_level == MEDICAL`, 1.25x when `special_care_level == BEHAVIORAL`, and none (1.0x) when `NONE`. A peak surcharge of ten percent of the baseline is added when, at the time the reservation is recorded, the shelter's utilization — defined as `reserved_slots` divided by `boarding_capacity` — stands at eighty percent or higher; the threshold and surcharge are the `PEAK_UTILIZATION` and `PEAK_SURCHARGE` constants respectively. The resulting sum is rounded half up to whole cents. Because the surcharge is snapshotted at reservation time, two otherwise-identical reservations created on different sides of the 0.8 utilization line will carry different quotes.

Check-in at `POST /shelters/{sid}/boarding-reservations/{rid}/check-in` requires the current moment to be within the `EARLY_CHECKIN_GRACE_HOURS` window of `check_in_date` (attempts sooner return `ERR_TOO_EARLY_FOR_CHECKIN`) and revalidates vaccination compliance. On success the reservation moves to `ACTIVE`; if the animal was `AVAILABLE`, its status moves to `BOARDING_ONLY`, otherwise it is left alone. Check-out at `POST /shelters/{sid}/boarding-reservations/{rid}/check-out` transitions the reservation to `COMPLETED`, recomputes `final_total` from the actual check-out date (the peak surcharge is NOT re-evaluated — only `nights` changes), decrements `reserved_slots`, and moves the animal back to `AVAILABLE` if the completed reservation was the sole reason for its `BOARDING_ONLY` status. A reservation may be cancelled from `RESERVED` or `ACTIVE` via `POST /shelters/{sid}/boarding-reservations/{rid}/cancel` — by a coordinator or the adopter-owner — or automatically by the system when the animal is adopted or the shelter is suspended; cancellation decrements `reserved_slots`, fails any `PENDING` settlement for the reservation, and un-pins the animal's `BOARDING_ONLY` if applicable. Settlement is the last act, performed by the finance officer through `POST /shelters/{sid}/boarding-reservations/{rid}/settle`, which requires a `COMPLETED` settlement for `(BOARDING, reservation_id)` (else `ERR_FEE_NOT_SETTLED`) and moves the reservation to the terminal `SETTLED` state. Listing is available through `GET /shelters/{sid}/boarding-reservations` with optional `status` and `animal_id` filters.

### 3.7. Capacity Accounting

Shelter occupancy is a pure derivation. `reserved_slots` equals the count of `BoardingReservation` rows at that shelter whose `status` is `RESERVED` or `ACTIVE`; `available_slots` is `boarding_capacity − reserved_slots`, clamped at zero. The counter is atomically incremented on transition into `RESERVED` and atomically decremented on any exit from `RESERVED` or `ACTIVE` (cancel, check-out, or cascading adoption finalization). When two reservations race for the last open slot, exactly one succeeds and the loser receives `ERR_SHELTER_AT_CAPACITY` as enumerated in §2.8. A shelter transition to `SUSPENDED` status likewise refuses new reservations.

### 3.8. Fee Settlement Lifecycle

All monetary exchange flows through the `FeeSettlement` resource. `POST /fee-settlements` creates a `PENDING` row with `subject_type` (`ADOPTION` or `BOARDING`), `subject_id` (pointing at an `AdoptionApplication.id` or a `BoardingReservation.id`), the declared `amount` in cents, and the payment `method` (`CARD`, `BANK_TRANSFER`, or `CASH`). The amount is not validated at creation — it is validated at capture.

`POST /fee-settlements/{id}/capture` is the finance officer's tool to realise the payment. It demands that the subject still be in a settle-eligible state (`APPROVED` for adoption, `COMPLETED` for boarding; else `ERR_INVALID_STATE`), that no other `COMPLETED` settlement already exists for the same `(subject_type, subject_id)` pair (else `ERR_DUPLICATE_SETTLEMENT`), and that the `amount` exactly match the authoritative figure — `pinned_fee` for an adoption subject, `quoted_total` for a boarding reservation that has not yet checked out, or `final_total` after check-out (else `ERR_AMOUNT_MISMATCH`). When all checks pass, the settlement moves to `COMPLETED` and its `settled_at` is stamped with the server clock. `POST /fee-settlements/{id}/refund` is available from `COMPLETED` provided the subject is not already in a terminal `FINALIZED`/`SETTLED` state; if the underlying adoption is still in `APPROVED`, the refund cascade-rejects it with `ERR_FEE_REFUNDED`, releasing the held animal. A `PENDING` settlement whose subject is subsequently cancelled or withdrawn is transitioned automatically by the system to `FAILED`. Settlements are retrievable through `GET /fee-settlements/{id}`.

## 4. Endpoint Definitions

All mutation endpoints that create a brand-new resource respond with HTTP `201`; mutation endpoints that modify an existing resource (state transitions, patches, captures, refunds, cancellations) respond with `200`. List and get endpoints return `200`. Request bodies and response bodies are not exhaustively enumerated in the table below — refer to §3 for each workflow's inputs, outputs, and side effects.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/shelters` | Create a shelter | `ShelterAdmin` |
| GET | `/shelters` | List shelters | `Any` |
| GET | `/shelters/{sid}` | Get a shelter | `Any` |
| POST | `/shelters/{sid}/animals` | Create an animal record | `ShelterAdmin` |
| GET | `/shelters/{sid}/animals` | List animals at a shelter | `Any` |
| GET | `/shelters/{sid}/animals/{aid}` | Get an animal | `Any` |
| PATCH | `/shelters/{sid}/animals/{aid}` | Update animal fields (with OCC) | `ShelterAdmin` |
| POST | `/shelters/{sid}/animals/{aid}/vaccinations` | Record a vaccination | `ShelterAdmin`, `Veterinarian` |
| GET | `/shelters/{sid}/animals/{aid}/vaccinations` | List vaccinations | `Any` |
| GET | `/shelters/{sid}/animals/{aid}/compliance` | Get vaccination compliance summary | `Any` |
| POST | `/adopters` | Register an adopter | `Adopter`, `ShelterAdmin` |
| GET | `/adopters/{id}` | Get an adopter | `Adopter`, `AdoptionReviewer`, `AdoptionApprover`, `ShelterAdmin` |
| POST | `/adopters/{id}/home-visits` | Schedule a home visit | `AdoptionReviewer` |
| GET | `/adopters/{id}/home-visits` | List home visits for an adopter | `AdoptionReviewer`, `AdoptionApprover`, `Adopter` |
| POST | `/adopters/{id}/home-visits/{hvId}/submit` | Submit home visit assessment | `HomeVisitInspector` |
| POST | `/adopters/{id}/home-visits/{hvId}/cancel` | Cancel a scheduled home visit | `Adopter`, `HomeVisitInspector` |
| POST | `/adoption-applications` | Submit an adoption application | `Adopter` |
| GET | `/adoption-applications` | List applications | `AdoptionReviewer`, `AdoptionApprover`, `ShelterAdmin` |
| GET | `/adoption-applications/{id}` | Get an application | `AdoptionReviewer`, `AdoptionApprover`, `Adopter`, `ShelterAdmin` |
| POST | `/adoption-applications/{id}/begin-review` | Move application to `UNDER_REVIEW` | `AdoptionReviewer` |
| POST | `/adoption-applications/{id}/request-home-visit` | Require a home visit | `AdoptionReviewer` |
| POST | `/adoption-applications/{id}/approve` | Approve an application | `AdoptionApprover` |
| POST | `/adoption-applications/{id}/reject` | Reject an application | `AdoptionApprover` |
| POST | `/adoption-applications/{id}/finalize` | Finalize an adoption | `AdoptionApprover` |
| POST | `/adoption-applications/{id}/withdraw` | Withdraw an application | `Adopter` |
| POST | `/shelters/{sid}/boarding-reservations` | Reserve boarding for an animal | `BoardingCoordinator`, `Adopter` |
| GET | `/shelters/{sid}/boarding-reservations` | List boarding reservations | `Any` |
| POST | `/shelters/{sid}/boarding-reservations/{rid}/check-in` | Check in a boarding animal | `BoardingCoordinator` |
| POST | `/shelters/{sid}/boarding-reservations/{rid}/check-out` | Check out a boarding animal | `BoardingCoordinator` |
| POST | `/shelters/{sid}/boarding-reservations/{rid}/settle` | Mark a reservation `SETTLED` | `FinanceOfficer` |
| POST | `/shelters/{sid}/boarding-reservations/{rid}/cancel` | Cancel a reservation | `BoardingCoordinator`, `Adopter` |
| POST | `/fee-settlements` | Create a pending settlement | `FinanceOfficer`, `Adopter` |
| POST | `/fee-settlements/{id}/capture` | Capture payment | `FinanceOfficer` |
| POST | `/fee-settlements/{id}/refund` | Refund a completed settlement | `FinanceOfficer` |
| GET | `/fee-settlements/{id}` | Get a settlement | `FinanceOfficer`, `Adopter` |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_SCORE` | 400 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_SHELTER_NOT_FOUND` | 404 |
| `ERR_ANIMAL_NOT_FOUND` | 404 |
| `ERR_ADOPTER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_HOME_VISIT_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_HOME_VISIT_REQUIRED` | 409 |
| `ERR_HOME_VISIT_FAILED` | 409 |
| `ERR_VACCINATION_NON_COMPLIANT` | 409 |
| `ERR_ADOPTER_DISQUALIFIED` | 409 |
| `ERR_ANIMAL_UNAVAILABLE` | 409 |
| `ERR_ANIMAL_ALREADY_RESERVED` | 409 |
| `ERR_ANIMAL_NOT_BOARDABLE` | 409 |
| `ERR_SHELTER_AT_CAPACITY` | 409 |
| `ERR_TOO_EARLY_FOR_CHECKIN` | 409 |
| `ERR_AMOUNT_MISMATCH` | 409 |
| `ERR_DUPLICATE_SETTLEMENT` | 409 |
| `ERR_FEE_NOT_SETTLED` | 409 |
| `ERR_FEE_REFUNDED` | 409 |
| `ERR_STALE_PINNED_REFERENCE` | 409 |
| `ERR_ANIMAL_ADOPTED` | 409 |
