# Pet Adoption Boarding API — Product Requirements Document

## 1. Introduction

Across municipal and private animal shelters, the coordination of pet adoptions and temporary boarding arrangements remains a largely manual, error-prone process. Case workers juggle paper forms for adoption applications while veterinarians track vaccination compliance in separate spreadsheets, leading to gaps that allow non-compliant animals into adoption pools or boarding facilities operating beyond safe capacity. This API addresses those operational pain points by unifying adoption workflows, boarding logistics, vaccination compliance tracking, and financial settlement into a single platform.

The system models the full lifecycle of an animal through a shelter — from initial intake and health compliance verification, through adoption application processing with mandatory home assessments for certain species, to boarding reservation management with compatibility scoring and zone assignment. A structured approval chain ensures segregation of duties: frontline `CaseWorker` staff handle day-to-day intake, applications, and boarding operations; a `ShelterManager` provides oversight through approvals, financial controls, and compliance resolution; and a `Veterinarian` maintains medical records and can flag health or safety concerns through compliance holds.

Financial accountability is built into every transaction. Fee schedules define species-specific pricing with loyalty incentives and senior animal discounts, while invoices are automatically generated at approval or confirmation milestones and must be fully settled before adoptions can be completed. The platform enforces capacity constraints, date-overlap protections, and vaccination compliance checks at every critical juncture, ensuring that no animal enters a boarding facility or adoption pipeline without meeting the shelter's safety standards.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the individual making the request, and `X-User-Role`, which declares their operational capacity within the shelter system. The platform recognizes three roles:

- `ShelterManager` — Senior shelter administrator responsible for approvals, financial actions, compliance resolution, and shelter-level operations.
- `CaseWorker` — Frontline staff who handle animal registration, adopter onboarding, application processing, home visits, boarding operations, and payment collection.
- `Veterinarian` — Medical staff authorized to manage vaccination records and impose compliance holds for health or safety concerns.

Requests missing either header or containing an unrecognized role value are rejected with `ERR_AUTH_REQUIRED`. When a valid user attempts an operation outside the scope of their declared role, the system responds with `ERR_FORBIDDEN`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful responses (2xx status codes) conform to the following envelope:

```json
{
  "meta": {
    "api_request_id": "req_adopt_7f3a9b2e1d4c",
    "api_request_timestamp": "2026-03-15T14:22:08.471Z",
    "limit": 20,
    "offset": 0,
    "total_count": 47,
    "has_more": true
  },
  "response_type": "array",
  "data": []
}
```

#### Standard Error Response Format

All error responses (4xx status codes) use this envelope:

```json
{
  "meta": {
    "api_request_id": "req_board_4e8c1a6f29d0",
    "api_request_timestamp": "2026-03-15T14:22:09.832Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "ERR_BOARDING_CAPACITY_FULL",
    "message": "Shelter has reached maximum boarding capacity."
  }
}
```

Field semantics:

- `api_request_id`: A server-generated unique identifier for every request, prefixed with `req_`.
- `api_request_timestamp`: A server-generated ISO 8601 UTC timestamp with exactly three fractional digits (millisecond precision).
- `response_type`: One of `"object"` (single resource), `"array"` (list of resources), or `"error"` (failure response).
- `data`: Contains the business payload — a resource object, an array of resource objects, or an empty object for 2xx responses with no payload. Unless otherwise noted, create and modify operations return the created or updated resource. For error responses, `data` contains `error_id` (a machine-readable identifier) and `message` (a human-readable explanation).
- Pagination fields (`limit`, `offset`, `total_count`, `has_more`) appear in `meta` only for list endpoint responses.

### 2.3. Pagination

List endpoints accept two query parameters for pagination. The `limit` parameter controls the maximum number of items returned; it defaults to 20, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified.

Responses from list endpoints include the pagination fields `limit`, `offset`, `total_count`, and `has_more` within the `meta` object.

### 2.4. Common Resource Properties and Immutability Conventions

Every primary resource in the system — Shelters, Animals, Vaccination Records, Adopters, Adoption Applications, Home Visits, Boarding Reservations, Fee Invoices, Compliance Holds, and Fee Schedules — carries a standard set of system-managed fields:

- `id` (string): A unique, system-generated UUID.
- `created_at` (string): An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp, also with three fractional digits, reflecting the most recent modification to the resource.
- `version` (integer): A system-managed counter that increments with every mutation to the resource, including updates to computed fields.

The `BoardingMatch` entity is an exception: it is created once during reservation confirmation and carries only `id` and `created_at`. It does not include `updated_at` or `version`, as it is immutable after creation.

### 2.5. Vaccination Compliance and Health Safety

Animal welfare forms the foundation of all shelter operations. Before an animal can be made available for adoption or accepted into the boarding facility, it must satisfy the vaccination requirements defined for its species. Dogs require current `RABIES`, `DHPP`, and `BORDETELLA` vaccinations. Cats must have `RABIES` and `FVRCP` on file. Rabbits need `RHDV` coverage. Birds and animals classified as `OTHER` have no mandatory vaccination schedule.

For boarding operations specifically, an additional requirement applies: `BORDETELLA` vaccination is mandatory for all species except birds, regardless of the default species schedule. This heightened standard reflects the close-quarters environment of boarding facilities where respiratory disease transmission risk is elevated.

A vaccination record is considered valid only when its `expiry_date` has not yet passed. Compliance is recomputed whenever new vaccination records are added, when an animal's status changes, and on periodic system rechecks.

### 2.6. Compliance Holds and Animal Availability

The compliance hold mechanism provides a safety valve for situations requiring immediate intervention. When a `Veterinarian` or `ShelterManager` places a hold of severity `HIGH` or `CRITICAL` on an animal, that animal is automatically transitioned to `UNAVAILABLE` status — regardless of whether it was previously `AVAILABLE` or actively in `BOARDING`. An animal currently boarding under an active reservation is not forcibly removed; the reservation continues so the animal remains in care, but the animal's `adoption_eligible` flag is immediately set to false.

Resolution of compliance holds is restricted to the `ShelterManager` role and requires providing `resolution_notes` explaining how the concern was addressed. Once all holds of severity `HIGH` or `CRITICAL` have been resolved, the animal automatically reverts to `AVAILABLE`, and its `adoption_eligible` status is recomputed. Holds with severity `LOW` or `MEDIUM` do not trigger automatic status transitions but are still tracked for compliance scoring purposes.

### 2.7. Shelter Compliance Scoring

Each shelter maintains a `compliance_score` ranging from 0 to 100 that reflects overall vaccination compliance and hold activity across its animal population. The score starts from the ratio of vaccination-compliant animals to total non-adopted animals, expressed as a percentage. For each active compliance hold across any animal in the shelter, a penalty of five points is deducted. If a shelter has no non-adopted animals, the score defaults to 100. The final value is rounded to 2 decimal places using the round-half-up method. This score is recomputed whenever vaccination records are created, compliance holds are created or resolved, or animal statuses change.

### 2.8. Monetary Precision and Rounding

All monetary values within the system — fee amounts, invoice totals, tax calculations, discounts, and revenue balances — are handled with 2 decimal places of precision. The round-half-up method is used consistently for all rounding operations. Tax amounts, for instance, are calculated by multiplying the taxable amount by the applicable tax rate and rounding the result to 2 decimal places before combining with other line items. This precision requirement applies to stored values, computed fields, and all monetary figures returned in API responses.

### 2.9. Optimistic Concurrency Control

Endpoints that modify an existing resource accept an optional `version` field in the request body. When provided, the server compares the submitted version against the resource's current version. A mismatch results in rejection with `ERR_STALE_DATA`, signaling that another operation has modified the resource since the client last read it. If the `version` field is omitted from the request body entirely, the server proceeds without a concurrency check, allowing the mutation unconditionally.

### 2.10. Cascading State Propagation and Hierarchical Consistency

Operations on one resource frequently trigger automatic transitions in related resources to maintain system-wide consistency. When an adoption application is approved, the associated animal transitions to `ADOPTION_PENDING`. When a boarding reservation is checked in, the shelter's `current_boarding_count` increments and the animal moves to `BOARDING` status (for shelter-owned animals). When a compliance hold is resolved, the animal's eligibility and potentially its availability status are recomputed.

Each of these cascading mutations independently updates the affected resource's `updated_at` timestamp and increments its `version`. The system guarantees that these propagations occur atomically within the triggering operation — there is no window in which dependent resources reflect an inconsistent state.

### 2.11. Nested Resource Validation and Path Resolution

When a request targets a resource identified by path parameters, the system validates each identifier in left-to-right order. If any identifier in the path does not correspond to an existing resource, the request is rejected immediately with the appropriate `404` error for the first missing resource. For example, referencing a non-existent shelter in any path that includes `{shelterId}` would yield `ERR_SHELTER_NOT_FOUND` before subsequent identifiers are evaluated.

Foreign key references in request bodies are similarly validated: an `animal_id` pointing to a non-existent animal produces `ERR_ANIMAL_NOT_FOUND`, an `adopter_id` referencing an unknown adopter produces `ERR_ADOPTER_NOT_FOUND`, and so on.

## 3. Business Logic & Workflows

### 3.1. Shelter Establishment and Operational Control

A `ShelterManager` establishes a new shelter by providing a `name`, physical `address`, and `boarding_capacity` — the maximum number of animals the facility can board simultaneously. Upon creation, the shelter enters `OPEN` status with all computed counters initialized: `current_boarding_count` at zero, `adoption_count` at zero, `compliance_score` at 100, and `revenue_balance` at zero.

Operational control over a shelter includes the ability to suspend and reopen it. Suspension blocks all new adoption applications and boarding reservations from being accepted, though existing in-progress operations — applications already under review, reservations already confirmed — continue unimpeded. Attempting to submit a new application or boarding reservation against a suspended shelter triggers `ERR_SHELTER_SUSPENDED`. Before a suspended shelter can be reopened, the system verifies that no animal within that shelter carries an active compliance hold of `CRITICAL` severity; otherwise, the reopen request fails with `ERR_COMPLIANCE_HOLD_ACTIVE`.

### 3.2. Animal Intake, Registration, and Availability

When an animal arrives at a shelter, a `CaseWorker` registers it by recording its `shelter_id`, `name`, `species` (one of `DOG`, `CAT`, `RABBIT`, `BIRD`, or `OTHER`), `breed`, `age_months`, `weight_kg`, and `temperament` (classified as `CALM`, `MODERATE`, `ENERGETIC`, or `AGGRESSIVE`). An optional `special_needs` array captures tags such as `MEDICATION_REQUIRED`, `DIET_RESTRICTED`, or `MOBILITY_LIMITED` that inform both care protocols and boarding compatibility. The animal enters `INTAKE` status with its `vaccination_compliant` flag computed immediately from existing records.

Transitioning an animal from `INTAKE` to `AVAILABLE` requires explicit action via the make-available endpoint. This transition is gated by two preconditions: the animal must be `vaccination_compliant`, and there must be no active compliance hold of severity `HIGH` or `CRITICAL`. Failure on the vaccination check yields `ERR_VACCINATION_NOT_COMPLIANT`; an active high-severity hold produces `ERR_COMPLIANCE_HOLD_ACTIVE`. Once available, the system derives the animal's `adoption_eligible` flag — true only when `vaccination_compliant` is true, status is `AVAILABLE`, and no active compliance hold exists. The `boarding_compatible_tags` array is also computed at this point, aggregating the animal's `species`, `temperament`, and `special_needs` into a set of tags used for boarding compatibility analysis.

A `CaseWorker` may later update mutable fields on an animal profile — `name`, `breed`, `age_months`, `weight_kg`, `temperament`, or `special_needs` — through a PATCH operation that accepts an optional `version` for concurrency control. Any such update triggers recomputation of `boarding_compatible_tags` and `adoption_eligible`.

### 3.3. Adopter Registration and Home Assessment

Prospective adopters are registered by a `CaseWorker` with their `shelter_id`, `full_name`, `email`, `phone`, `home_type` (one of `HOUSE`, `APARTMENT`, `FARM`, or `OTHER`), `has_yard` flag, `has_other_pets` flag, and an optional `other_pet_species` array. New adopters start as `ACTIVE` with `adoption_history_count` at zero and `home_visit_passed` set to false.

Home visits serve as a critical safeguard for certain adoption scenarios. When an adoption application reaches the `UNDER_REVIEW` stage, the reviewing `CaseWorker` may determine that a home assessment is necessary and flag the application accordingly. A `CaseWorker` then schedules a home visit by providing the `adopter_id`, the triggering `application_id`, and a `scheduled_date`. The system automatically assigns the creating case worker as the `case_worker_id` for the visit and transitions the associated application to `HOME_VISIT_SCHEDULED`.

During the assessment, the assigned case worker evaluates four criteria. Adequate yard space carries a weight of 25 points, sufficient living space accounts for 30 points, the absence of safety hazards contributes 25 points (finding hazards scores zero for this criterion), and compatibility with existing pets is worth 20 points. The `overall_score` sums these weighted assessments, yielding a maximum possible score of 100.

When the animal in question belongs to a species that does not require outdoor space — specifically `CAT`, `BIRD`, or `RABBIT` — the yard criterion weight drops to zero, and the space adequacy weight increases to 45. Under this variant, the maximum achievable score is 90, though the passing threshold remains unchanged.

An `overall_score` of 70 or above results in a `PASS`. Scores between 50 and 69 yield a `CONDITIONAL_PASS`, which is still sufficient to advance the application. Scores below 50 produce a `FAIL`. Only the case worker originally assigned to the visit (identified by `case_worker_id`) may complete it; attempts by another case worker are rejected with `ERR_ASSESSOR_MISMATCH`. The assessment requires all four boolean inputs: `yard_adequate`, `space_adequate`, `safety_hazards_found`, and `existing_pets_compatible`, along with inspector `notes`.

If the visit results in `PASS` or `CONDITIONAL_PASS`, the adopter's `home_visit_passed` flag updates to true, and the associated application advances to `REVIEWED`. A `FAIL` result automatically rejects the application with the reason "Home visit failed" and reverts the animal to `AVAILABLE` if it had been moved to `ADOPTION_PENDING`.

Cancellation of a scheduled home visit returns the application to `HOME_VISIT_REQUIRED`, allowing a new visit to be arranged. If a visit's `scheduled_date` passes without completion, the system automatically expires the visit and similarly reverts the application to `HOME_VISIT_REQUIRED`.

A `ShelterManager` may blacklist an adopter, transitioning their status to `BLACKLISTED`. Upon blacklisting, all of that adopter's applications currently in `SUBMITTED` or `UNDER_REVIEW` status are automatically withdrawn.

### 3.4. The Adoption Application Lifecycle

Adoption applications follow a carefully structured approval chain that enforces segregation of duties between case workers and shelter managers. A `CaseWorker` initiates the process by submitting an application with the target `animal_id`, the `adopter_id`, and a `reason` explaining why the adopter wants this particular animal. The system derives the `shelter_id` from the animal's record and sets the initial status to `SUBMITTED`. At submission time, the animal must be `AVAILABLE` (otherwise `ERR_ANIMAL_NOT_AVAILABLE`), the adopter must be `ACTIVE` (otherwise `ERR_ADOPTER_BLACKLISTED`), and the shelter must be `OPEN` (otherwise `ERR_SHELTER_SUSPENDED`).

When a `CaseWorker` begins reviewing the application, the status transitions to `UNDER_REVIEW`. At this point, the system pins two critical version numbers: the current `animal_version` from the Animal record and the `adopter_version` from the Adopter record. These snapshots ensure that the data reviewed during the assessment remains consistent through to final approval. The `reviewer_id` is set to the acting case worker's identity. Only this reviewer may perform subsequent review operations on the application — attempts by a different case worker are rejected with `ERR_REVIEWER_MISMATCH`.

From `UNDER_REVIEW`, the reviewer has two paths. If a home visit is deemed necessary — mandatory for dogs, at the reviewer's discretion for other species — the application moves to `HOME_VISIT_REQUIRED`. Alternatively, the reviewer may complete the review directly, advancing the application to `REVIEWED`. However, completing the review for a dog adoption requires that the adopter has already passed a home visit (`home_visit_passed` must be true); failing this check raises `ERR_HOME_VISIT_REQUIRED`. For cats, birds, and rabbits, the home visit requirement is waived.

Final approval rests with a `ShelterManager`, who must be a different person than the reviewer — the `approver_id` must differ from the `reviewer_id`, enforcing segregation of duties. Violation triggers `ERR_SELF_APPROVAL`. Before granting approval, the system performs several consistency checks: the pinned `animal_version` must still match the Animal's current version (otherwise `ERR_STALE_ANIMAL_DATA`), the pinned `adopter_version` must match the Adopter's current version (otherwise `ERR_STALE_ADOPTER_DATA`), the animal must remain `AVAILABLE` (otherwise `ERR_ANIMAL_NOT_AVAILABLE`), and the shelter must still be `OPEN` (otherwise `ERR_SHELTER_SUSPENDED`).

Upon approval, the animal transitions to `ADOPTION_PENDING` and its `adoption_eligible` flag is set to false. A `FeeInvoice` is automatically generated using the adoption fee calculation (detailed in section 3.7) and linked to the application via `fee_invoice_id`.

Completion of the adoption — the final step — is handled by a `CaseWorker` and requires the associated fee invoice to be in `PAID` status. If payment is outstanding, the request fails with `ERR_FEE_NOT_PAID`. Successful completion moves the animal to `ADOPTED` status, increments the shelter's `adoption_count`, and increments the adopter's `adoption_history_count`.

At any point before approval, a `CaseWorker` may withdraw the application, which transitions it to `WITHDRAWN`. If the animal had already moved to `ADOPTION_PENDING`, it reverts to `AVAILABLE`. If a home visit was `SCHEDULED`, it is automatically cancelled.

A `ShelterManager` may also reject a reviewed application by providing a `rejection_reason`. Rejection is terminal and does not trigger animal status changes unless the animal was already in `ADOPTION_PENDING` (which should not occur at the `REVIEWED` stage under normal flow).

### 3.5. Boarding Reservations and Facility Management

Boarding reservations accommodate animals whose owners need temporary care arrangements. A `CaseWorker` creates a reservation by specifying the `shelter_id`, `animal_id`, `owner_name`, `owner_contact`, planned `check_in_date`, planned `check_out_date`, and optional `special_instructions`. The system validates that `check_out_date` falls after `check_in_date` (otherwise `ERR_INVALID_DATES`) and computes `duration_days` by taking the difference in seconds divided by 86,400, rounded up to the nearest whole day. The reservation begins in `REQUESTED` status.

Confirmation of a reservation is a `ShelterManager` action that triggers multiple validations. The animal must be `vaccination_compliant` — and for boarding purposes, this includes the additional `BORDETELLA` requirement for all species except birds. The shelter's `current_boarding_count` must be strictly less than its `boarding_capacity`; reaching the limit produces `ERR_BOARDING_CAPACITY_FULL`. There must be no date overlap with other `CONFIRMED` or `CHECKED_IN` reservations for the same animal; a conflict yields `ERR_BOARDING_DATE_OVERLAP`. The shelter must also be `OPEN`.

Upon confirmation, the system creates a `BoardingMatch` record that evaluates the compatibility of the incoming animal with those currently checked in. A `BoardingMatch` carries a `compatibility_score`, a `boarding_zone` assignment, and an array of `conflict_flags`. The match's `reservation_id`, `animal_id`, and `shelter_id` are set automatically. A fee invoice is also generated from the boarding fee calculation and linked to the reservation.

Check-in, performed by a `CaseWorker`, requires the reservation to be `CONFIRMED`. At check-in time, the animal's vaccination compliance is re-verified — an expiry occurring between confirmation and arrival causes `ERR_VACCINATION_NOT_COMPLIANT`. Additionally, any active compliance hold of severity `HIGH` or `CRITICAL` on the animal blocks check-in with `ERR_COMPLIANCE_HOLD_ACTIVE`. Successful check-in records the `actual_check_in` timestamp, increments the shelter's `current_boarding_count`, and transitions the animal to `BOARDING` status if it is shelter-owned.

Check-out records the `actual_check_out` timestamp, recomputes `duration_days` from the actual dates, adjusts the fee invoice line items if the actual duration differs from the planned duration, decrements the shelter's `current_boarding_count`, and returns the animal to `AVAILABLE` (if shelter-owned).

Cancellation of a reservation is permitted while the reservation is in `REQUESTED` or `CONFIRMED` status. If confirmed, the associated boarding match is voided. If a fee invoice exists and is `ISSUED`, it transitions to `VOID`. If the invoice has already been `PAID`, a refund is initiated.

### 3.6. Boarding Compatibility Scoring and Zone Assignment

When a boarding reservation is confirmed, the system evaluates how well the incoming animal fits with those already present in the facility. The algorithm starts from a base score of 100 and applies penalties based on the animals currently in `CHECKED_IN` status at the same shelter.

For each animal already boarded, a species mismatch between the incoming and resident animal incurs a penalty of 10 points. If either animal has an `AGGRESSIVE` temperament, a 25-point penalty is assessed. When the pairing involves an `ENERGETIC` animal alongside a `CALM` one, an additional 15 points are deducted. Each special need tag carried by the incoming animal contributes a further 5-point reduction. The `compatibility_score` is the base minus total penalties, floored at zero.

Zone assignment follows deterministic rules based on the incoming animal's profile. Animals with `AGGRESSIVE` temperament are placed in the `ISOLATION` zone. Those classified as `ENERGETIC` are assigned to the `ACTIVE` zone. Cats, birds, and rabbits receive the `SMALL_ANIMAL` zone. All remaining animals default to the `GENERAL` zone.

Conflict flags are generated to provide human-readable warnings: `AGGRESSIVE_NEAR_CALM` when an aggressive animal would be near a calm one, `SPECIES_MISMATCH` when different species share the facility, and similar diagnostic indicators derived from the penalty evaluation.

### 3.7. Fee Calculations and Invoice Lifecycle

The financial model rests on `FeeSchedule` entries that a `ShelterManager` configures per shelter. Each entry specifies a `fee_type` (one of `ADOPTION_BASE`, `BOARDING_DAILY`, `SPECIAL_NEEDS_SURCHARGE`, `VACCINATION_FEE`, or `LOYALTY_DISCOUNT`), a target `species` (or `ALL` for universal rates), an `amount`, and a validity window defined by `effective_from` and an optional `effective_to`. The `effective_to` date, if provided, must be after `effective_from` — otherwise `ERR_INVALID_DATES`. The system computes `is_active` based on whether the current time falls within the effective period.

**Adoption fee calculation** occurs when an application is approved. The base fee is looked up from the `FeeSchedule` for the `ADOPTION_BASE` type matching the animal's species. Senior animals — those aged seven years (84 months) or older — receive a fifty percent reduction on the base fee. Each special need tag on the animal adds a surcharge sourced from the `SPECIAL_NEEDS_SURCHARGE` schedule entry for the species. Adopters who have previously completed two or more adoptions qualify for a loyalty discount: the `LOYALTY_DISCOUNT` rate (a percentage from the `ALL`-species schedule entry) is applied against the combined base fee and surcharge total. Tax is computed on the net amount (subtotal minus discount) using the shelter's configured `tax_rate`, rounded to 2 decimal places via round-half-up. The final `total_amount` is the subtotal minus discount plus tax.

**Boarding fee calculation** is triggered at reservation confirmation and adjusted at check-out. The daily rate comes from the `BOARDING_DAILY` schedule entry for the animal's species. Duration in days is computed by dividing the time span between check-in and check-out (in seconds) by 86,400 and rounding up. Each special need tag adds a daily surcharge from the `SPECIAL_NEEDS_SURCHARGE` entry. Stays exceeding two weeks — more than fourteen days — qualify for a long-stay discount: the effective daily rate (base plus surcharges) is reduced by ten percent. The `subtotal` is the effective daily rate multiplied by the number of days. Tax is applied to the subtotal and rounded using the same 2-decimal-place, round-half-up method. At check-out, if actual dates differ from planned dates, the invoice is recalculated using `actual_check_in` and `actual_check_out` and the line items are adjusted accordingly.

Fee invoices begin in `DRAFT` status and transition to `ISSUED` automatically upon the triggering event (adoption approval or boarding confirmation). Line items are calculated from the active fee schedule at that moment. Payments are recorded by a `CaseWorker` providing an `amount`. The `amount` must be positive and must not exceed the `balance_due`, or the request is rejected with `ERR_PAYMENT_AMOUNT_INVALID`. If the cumulative `paid_amount` equals the `total_amount`, the invoice moves to `PAID`; otherwise it moves to `PARTIALLY_PAID`. Each payment increases the shelter's `revenue_balance`.

A `ShelterManager` may refund a `PAID` or `PARTIALLY_PAID` invoice, which sets the `refund_amount` to the `paid_amount` and decreases the shelter's `revenue_balance`. Voiding is permitted on `DRAFT` or `ISSUED` invoices only when no payments have been recorded (`paid_amount` must be zero); otherwise `ERR_INVOICE_HAS_PAYMENTS` is raised. The shelter's `revenue_balance` reflects the net of all payments received minus all refunds issued across its invoices.

### 3.8. Concurrency Safeguards and Race Condition Handling

Several critical operations are subject to concurrency constraints beyond the general optimistic concurrency mechanism. At most one adoption application may be in `APPROVED` or `COMPLETED` status for any given animal at any time — a second approval attempt for the same animal fails with `ERR_ANIMAL_NOT_AVAILABLE`. Similarly, at most one confirmed or checked-in boarding reservation may exist for an animal within any given date range; conflicting confirmations produce `ERR_BOARDING_DATE_OVERLAP`.

When a compliance hold arrives simultaneously with an adoption approval for the same animal, the system enforces first-writer-wins semantics on the animal's status. If the hold is written first, the approval encounters a non-available animal and fails with `ERR_COMPLIANCE_HOLD_ACTIVE`. If the approval writes first, the hold may still transition the animal to `UNAVAILABLE`, but the already-approved application continues its lifecycle.

Boarding check-in validates vaccination compliance at execution time, not at confirmation time. If a vaccination record expires between confirmation and the check-in attempt, the check-in fails with `ERR_VACCINATION_NOT_COMPLIANT`. Similarly, fee invoice payment and voiding operations employ first-writer-wins on the invoice status, with the losing operation receiving `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create new standalone resources return a `201 Created` status code. Operations that modify an existing resource — including state transitions, payments, and profile updates — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------- |
| POST | `/shelters` | Create a new shelter | ShelterManager |
| GET | `/shelters` | List all shelters | ShelterManager, CaseWorker, Veterinarian |
| GET | `/shelters/{shelterId}` | Get a specific shelter | ShelterManager, CaseWorker, Veterinarian |
| POST | `/shelters/{shelterId}/suspend` | Suspend shelter operations | ShelterManager |
| POST | `/shelters/{shelterId}/reopen` | Reopen a suspended shelter | ShelterManager |
| POST | `/animals` | Register a new animal | CaseWorker |
| GET | `/animals` | List animals with optional filters | ShelterManager, CaseWorker, Veterinarian |
| GET | `/animals/{animalId}` | Get a specific animal | ShelterManager, CaseWorker, Veterinarian |
| PATCH | `/animals/{animalId}` | Update animal details | CaseWorker |
| POST | `/animals/{animalId}/make-available` | Transition animal to available | CaseWorker |
| POST | `/vaccination-records` | Add a vaccination record | Veterinarian |
| GET | `/vaccination-records` | List vaccination records | ShelterManager, CaseWorker, Veterinarian |
| GET | `/vaccination-records/{recordId}` | Get a specific vaccination record | ShelterManager, CaseWorker, Veterinarian |
| POST | `/adopters` | Register a new adopter | CaseWorker |
| GET | `/adopters` | List adopters with optional filters | ShelterManager, CaseWorker |
| GET | `/adopters/{adopterId}` | Get a specific adopter | ShelterManager, CaseWorker |
| PATCH | `/adopters/{adopterId}` | Update adopter details | CaseWorker |
| POST | `/adopters/{adopterId}/blacklist` | Blacklist an adopter | ShelterManager |
| POST | `/adoption-applications` | Submit a new adoption application | CaseWorker |
| GET | `/adoption-applications` | List adoption applications | ShelterManager, CaseWorker |
| GET | `/adoption-applications/{applicationId}` | Get a specific application | ShelterManager, CaseWorker |
| POST | `/adoption-applications/{applicationId}/start-review` | Begin reviewing an application | CaseWorker |
| POST | `/adoption-applications/{applicationId}/require-home-visit` | Flag application as requiring home visit | CaseWorker |
| POST | `/adoption-applications/{applicationId}/complete-review` | Complete review of an application | CaseWorker |
| POST | `/adoption-applications/{applicationId}/approve` | Approve an adoption application | ShelterManager |
| POST | `/adoption-applications/{applicationId}/reject` | Reject an adoption application | ShelterManager |
| POST | `/adoption-applications/{applicationId}/complete` | Complete an approved adoption | CaseWorker |
| POST | `/adoption-applications/{applicationId}/withdraw` | Withdraw an adoption application | CaseWorker |
| POST | `/home-visits` | Schedule a home visit | CaseWorker |
| GET | `/home-visits` | List home visits | ShelterManager, CaseWorker |
| GET | `/home-visits/{homeVisitId}` | Get a specific home visit | ShelterManager, CaseWorker |
| POST | `/home-visits/{homeVisitId}/complete` | Complete a home visit with assessment | CaseWorker |
| POST | `/home-visits/{homeVisitId}/cancel` | Cancel a scheduled home visit | CaseWorker |
| POST | `/boarding-reservations` | Request a boarding reservation | CaseWorker |
| GET | `/boarding-reservations` | List boarding reservations | ShelterManager, CaseWorker |
| GET | `/boarding-reservations/{reservationId}` | Get a specific boarding reservation | ShelterManager, CaseWorker |
| POST | `/boarding-reservations/{reservationId}/confirm` | Confirm a boarding reservation | ShelterManager |
| POST | `/boarding-reservations/{reservationId}/check-in` | Check in animal for boarding | CaseWorker |
| POST | `/boarding-reservations/{reservationId}/check-out` | Check out animal from boarding | CaseWorker |
| POST | `/boarding-reservations/{reservationId}/cancel` | Cancel a boarding reservation | CaseWorker |
| GET | `/fee-invoices` | List fee invoices | ShelterManager, CaseWorker |
| GET | `/fee-invoices/{invoiceId}` | Get a specific fee invoice | ShelterManager, CaseWorker |
| POST | `/fee-invoices/{invoiceId}/pay` | Record a payment against an invoice | CaseWorker |
| POST | `/fee-invoices/{invoiceId}/refund` | Refund a paid invoice | ShelterManager |
| POST | `/fee-invoices/{invoiceId}/void` | Void an unpaid invoice | ShelterManager |
| POST | `/compliance-holds` | Create a compliance hold on an animal | Veterinarian, ShelterManager |
| GET | `/compliance-holds` | List compliance holds | ShelterManager, CaseWorker, Veterinarian |
| GET | `/compliance-holds/{holdId}` | Get a specific compliance hold | ShelterManager, CaseWorker, Veterinarian |
| POST | `/compliance-holds/{holdId}/resolve` | Resolve a compliance hold | ShelterManager |
| POST | `/fee-schedules` | Create a fee schedule entry | ShelterManager |
| GET | `/fee-schedules` | List fee schedules | ShelterManager, CaseWorker |
| GET | `/fee-schedules/{feeScheduleId}` | Get a specific fee schedule | ShelterManager, CaseWorker |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATES` | 400 Bad Request |
| `ERR_SHELTER_NOT_FOUND` | 404 Not Found |
| `ERR_ANIMAL_NOT_FOUND` | 404 Not Found |
| `ERR_ADOPTER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_HOME_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_VACCINATION_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SHELTER_SUSPENDED` | 409 Conflict |
| `ERR_ANIMAL_NOT_AVAILABLE` | 409 Conflict |
| `ERR_ADOPTER_BLACKLISTED` | 409 Conflict |
| `ERR_VACCINATION_NOT_COMPLIANT` | 409 Conflict |
| `ERR_COMPLIANCE_HOLD_ACTIVE` | 409 Conflict |
| `ERR_SELF_APPROVAL` | 409 Conflict |
| `ERR_STALE_ANIMAL_DATA` | 409 Conflict |
| `ERR_STALE_ADOPTER_DATA` | 409 Conflict |
| `ERR_HOME_VISIT_REQUIRED` | 409 Conflict |
| `ERR_REVIEWER_MISMATCH` | 409 Conflict |
| `ERR_ASSESSOR_MISMATCH` | 409 Conflict |
| `ERR_BOARDING_DATE_OVERLAP` | 409 Conflict |
| `ERR_BOARDING_CAPACITY_FULL` | 409 Conflict |
| `ERR_FEE_NOT_PAID` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_INVALID` | 400 Bad Request |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_STALE_DATA` | 409 Conflict |
