# WIC Benefits Management API — Product Requirements Document

## 1. Introduction

The Special Supplemental Nutrition Program for Women, Infants, and Children (WIC) serves a population whose eligibility and entitlements turn on a chain of legally mandated determinations: household income measured against federal poverty guidelines, nutritional risk assessed by a credentialed professional, certification for a category-specific period, and the issuance of a food package onto an electronic benefit account that participants draw down at authorized vendors. This API is the system of record for that chain. It governs local agencies and their clinics and vendors, the households and participants they serve, the applications that move a participant from applicant to certified, and the downstream artifacts — certifications, food prescriptions, EBT accounts, redemptions, clinic appointments, and breastfeeding peer-support sessions — that flow from a successful certification.

Two cross-cutting concerns shape almost every rule in this document. The first is **integrity of public funds**: every unit of food benefit issued must be conserved across issuance, redemption, and void, and a participant must never be certified in two places at once. The second is **segregation of duties**: the staff member who determines a household's income may not also be the one who certifies the application, mirroring the program-integrity controls federal regulations require. The remainder of this document specifies the structural API contract (Section 2) and the business workflows and their interlocking rules (Section 3), followed by the endpoint and error catalogues (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Every entity in the system is a top-level collection addressed by its own identifier; there are no nested resource paths. Relationships between entities are carried as foreign-key fields inside request bodies and are discovered through filtered list endpoints rather than through URL nesting.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly three roles: `EligibilityClerk`, `CompetentProfessionalAuthority`, and `Participant`. A request that omits either header, or that carries a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the requested operation is rejected with `ERR_FORBIDDEN`.

The `EligibilityClerk` is front-desk staff: they create agencies, clinics, vendors, households, participants, and applications, attach income records, run income determination, manage the vendor lifecycle, and manage clinic appointments other than completion. The `CompetentProfessionalAuthority` — abbreviated CPA throughout this document — is a credentialed nutrition professional who performs the risk assessment, approves or denies and thereby certifies applications, manages the certification lifecycle, issues food prescriptions, completes clinic appointments, and runs peer-support sessions. The `Participant` is a WIC participant who views their own participant record and EBT account and records their own redemptions.

Two of these roles use **opaque** identities. When `X-User-Role` is `EligibilityClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a scaffold transition writes it — specifically as `determined_by_user_id` on an `Application` when that clerk runs income determination — but does not compare it to any entity's `id`. When `X-User-Role` is `CompetentProfessionalAuthority`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records it as `certified_by_user_id` on an `Application` at approval, but otherwise does not compare it to any entity's `id`. The one comparison the server does make between these two opaque identifiers is the segregation-of-duties check described in Section 3. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a participant compare the resource's participant foreign-key field to `X-User-ID`, so a participant may read and act only on their own participant record, EBT account, and redemptions.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most top-level resources — agencies, clinics, vendors, households, participants, applications, certifications, food prescriptions, EBT accounts, clinic appointments, and peer-support sessions — carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp indicating when the resource was last modified; it is refreshed on every mutation of the resource.
- **`version`** — an integer that begins at 1 on creation and increments by one with every subsequent mutation of the resource. It is the basis for optimistic concurrency control described in Section 2.7.

Two entities are deliberate exceptions because they are append-only evidence rather than mutable records. An `IncomeRecord` (a single pay stub attached to an application) and a `Redemption` (a single EBT draw-down event) carry only `id` and `created_at`; they have neither `updated_at` nor `version`, because once written they are never modified. Wherever a workflow refers to "bumping" or "incrementing the version" of a parent, it refers only to entities that carry `version`.

When a derived field on an entity changes as a side effect of some operation — for example an `EbtAccount`'s reconciled value totals, or a `Participant`'s `status` or `priority_level` — that change is itself a mutation of the owning entity: its `updated_at` is refreshed and, where the entity carries `version`, its `version` is incremented. Every entity that moves through a lifecycle carries a `status` field whose value is always one of the exact uppercase state strings enumerated for that entity in Section 3.

### 2.5. The Deterministic Agency Clock

Time in this system is not wall-clock time. Each `Agency` carries a deterministic clock exposed as `current_utc`, which defaults to `1970-01-01T00:00:00.000Z` when the agency is created and advances only when an operator explicitly sets it. Every temporal decision — whether a certification period has ended, whether an appointment is in the past, how many days remain in the current issuance month for proration — reads the owning agency's `current_utc` rather than the host's wall clock. A separate operator capability advances the clock to a supplied instant (carried in the request as `to_iso8601` alongside the target `agency_id`), and another operator capability performs a sweep that expires due certifications; both are described in Section 3. This determinism is what makes certification expiry, proration, and appointment-past checks reproducible.

### 2.6. Hierarchical Consistency and Cascading Side Effects

Operations in this system frequently mutate more than one entity. When a certifying approval succeeds, it does not merely close the application — it mints a certification, flips the participant to active, debits the agency's caseload counter, and opens an EBT account. When a certification is terminated or expires, the effect cascades downward through the participant, the participant's outstanding food prescriptions, and the EBT account's value reconciliation. Every such cascade is specified in full in Section 3; the governing principle here is that the server performs the entire cascade as one logical operation, and each entity it touches independently has its `updated_at` refreshed and, where applicable, its `version` incremented. The server transitions parent or child resources automatically when criteria are satisfied — for example, advancing a food prescription to a redeemed or voided state — without requiring a separate client request against that specific resource.

For any request that references resources both in the path and in the body, the server validates existence left to right: the path identifier is resolved first, then each foreign-key identifier in the body, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource, guarding against a client overwriting state it has not observed.

Scheduling a clinic appointment requires `expected_clinic_version` in the request body, carrying the client's last observed `version` of the target `Clinic`. Because a previously scheduled appointment legitimately occupies an interval and advances the clinic's `version`, a client that read the clinic before that appointment was placed would otherwise schedule against an outdated occupancy picture. If `expected_clinic_version` does not match the clinic's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Issuing a food prescription requires `expected_participant_version` in the request body, carrying the client's last observed `version` of the `Participant`. A prior issuance, or a certification suspend-or-reinstate cascade, legitimately advances the participant's `version`, so a stale issuer's view of the participant — and of the EBT balance it would top up — must be rejected. If `expected_participant_version` does not match the participant's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Endpoints not named in this subsection do not perform an OCC check.

### 2.8. Monetary Values, Units, and Precision

All money in this system is carried as integer cents; there are no fractional cents anywhere. Food-package value, EBT account totals, and redemption value are all integers. Where a calculation produces an intermediate division (for example averaging pay amounts before annualizing, or applying a proration factor), the rounding rule for that specific step is stated with the calculation in Section 3.

Two computations produce annualized dollar figures rather than cents: an application's `annual_income_determined` and `income_limit` are dollar amounts rounded to exactly 2 decimal places using the round-half-up convention. The income-eligibility comparison between them is exact and its boundary is inclusive.

### 2.9. Validation Ordering

When multiple checks apply to a single request, the server evaluates them in a fixed priority order, and the first check to fail determines the response. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN`); then existence of every referenced resource, validated left to right with path identifiers ahead of body foreign keys (`ERR_NOT_FOUND`); then well-formedness of the request body — required fields present, enum values legal, integer fields non-negative (`ERR_INVALID_REQUEST`); then, on the two OCC-guarded writes, the optimistic-concurrency version check (`ERR_STALE_VERSION`); then the target resource's state legality for the requested transition (`ERR_INVALID_STATE`). Only after all of these pass does the server evaluate the operation's domain-specific business rules.

Among the domain-specific rules, the relative order also matters where several apply to the same endpoint. On approval the order is: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then dual participation (`ERR_DUAL_PARTICIPATION`), then the vendor-authorization check where applicable, then the eligibility gates (`ERR_INCOME_INELIGIBLE` before `ERR_RISK_INELIGIBLE`), then the temporal-overlap checks, and finally the fiscal and quota checks such as caseload capacity (`ERR_CASELOAD_EXCEEDED`). On a redemption the vendor-authorization check (`ERR_VENDOR_NOT_AUTHORIZED`) precedes the fiscal balance check (`ERR_INSUFFICIENT_BALANCE`). This ordering ensures, for instance, that a segregation-of-duties violation surfaces as `ERR_SEGREGATION_OF_DUTIES` rather than being masked by a later eligibility check.

## 3. Business Logic & Workflows

### 3.1. Establishing the Agency and Its Service Network

A `EligibilityClerk` stands up a local WIC agency by supplying its `name`, its two-letter `state_code`, and its `caseload_cap` — the maximum number of participants that may simultaneously hold an active certification under that agency. A freshly created agency begins with an `active_caseload_count` of 0 and its `current_utc` clock at the epoch default. The `active_caseload_count` is a derived counter: it is debited (incremented) by one each time a participant is certified and credited (decremented) by one when a participant's certification is terminated or expires.

Under an agency, the same clerk registers clinics and vendors. A clinic is created with its parent `agency_id`, a `name`, and an optional `appointment_buffer_minutes`; when omitted, the buffer defaults to 0, meaning back-to-back appointments are permitted because appointment intervals are treated as half-open. A vendor is registered with its `agency_id`, a `legal_name`, and a `peer_group` drawn from `SMALL`, `MEDIUM`, or `LARGE` for cost-containment grouping. A new vendor enters in `PENDING` status with `violation_points` at 0. Each of these collections can be listed and filtered by `agency_id` to discover the clinics and vendors belonging to an agency.

Households are the economic units against which income is measured. A household is created with its `agency_id`, a `household_size` counting the persons in the economic unit, an optional `pregnancy_count` (defaulting to 0) recording in-progress pregnancies, and an optional `adjunctive_program` (defaulting to `NONE`, otherwise one of `SNAP`, `MEDICAID`, or `TANF`). The `pregnancy_count` matters for the income test, and the `adjunctive_program` provides an automatic route to income eligibility, both as described in Section 3.3. Households can be listed and filtered by `agency_id`.

### 3.2. Enrolling Participants and Opening Applications

A clerk enrolls a `Participant` into a household by supplying the parent `household_id`, the participant's `full_name`, the last four digits of their social security number as `ssn_last4`, their WIC `category` (one of `PREGNANT`, `POSTPARTUM`, `BREASTFEEDING`, `INFANT`, or `CHILD`), and an optional `breastfeeding_opt_in` flag (defaulting to false) indicating whether the participant requests breastfeeding peer support. At creation the participant's `agency_id` is copied from the household, the participant starts in `APPLICANT` status, and the participant's `version` begins at 1. The pair of `full_name` and `ssn_last4` together forms the participant's dual-participation identity key, which the approval workflow uses to prevent the same person from being certified under two different households at once. A participant's `priority_level` — the WIC nutrition priority running from I through VII — remains null until certification assigns it. Participants can be listed and filtered by `household_id`.

To pursue certification, a clerk opens an `Application` referencing the `participant_id`, optionally specifying the `income_method` to use for the income determination (defaulting to `ANNUALIZE_RECENT`, the alternative being `AVERAGE_ALL`). A new application begins in `DRAFT` status. Its computed fields — `annual_income_determined`, `income_limit`, `income_eligible`, `total_risk_score`, `risk_eligible` — are all null at this point, as are the system-stamped `determined_by_user_id` and `certified_by_user_id`. The `risk_factor_codes` array is empty until risk is assessed. Applications can be listed and filtered by `participant_id`.

Income evidence is attached as one or more `IncomeRecord` entries, each referencing its `application_id` and carrying a `gross_amount_cents` figure for a single pay period and a `pay_frequency` of `WEEKLY`, `BIWEEKLY`, `MONTHLY`, or `ANNUAL`. The server assigns each income record a `sequence_index` in creation order within the application, starting at 0. This sequence index — never the record's `id` — is what pins the chronological processing order during income determination. Income records can be listed and filtered by `application_id`.

### 3.3. Income Determination

Income determination is the first state transition on an application: a clerk runs it to advance the application from `DRAFT` to `INCOME_DETERMINED`. The application must be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and at least one income record must already be attached (otherwise `ERR_NO_INCOME_RECORDS`). Running the determination stamps `determined_by_user_id` with the acting clerk's `X-User-ID`, computes the three income fields, and increments the application's `version` by one.

The system first computes the household's adjusted size by adding the household's `pregnancy_count` to its `household_size`, since each in-progress pregnancy counts as an additional person for the income test. From that adjusted size it looks up the annual federal poverty guideline: for an adjusted size of 1 through 8 the guideline is exactly 15060, 20440, 25820, 31200, 36580, 41960, 47340, and 52720 dollars respectively; for each person beyond 8, add 5380 dollars to the size-8 figure. The `income_limit` is that poverty guideline multiplied by 1.85 (the 185-percent WIC ceiling), rounded half-up to two decimal places.

The household's annualized income, `annual_income_determined`, depends on the chosen `income_method`. Annualizing a single pay figure means converting the cents amount to dollars (dividing by 100) and multiplying by the periods-per-year multiplier for its frequency: 52 for `WEEKLY`, 26 for `BIWEEKLY`, 12 for `MONTHLY`, and 1 for `ANNUAL`. The most recent income record is the one with the highest `sequence_index` — never the most recently created `id`. Under the `ANNUALIZE_RECENT` method, the system annualizes only that highest-sequence record, ignoring all earlier records, and rounds the result half-up to two decimal places. Under the `AVERAGE_ALL` method, the system first selects all income records whose `pay_frequency` equals the most recent record's frequency, takes the arithmetic mean of their `gross_amount_cents`, rounds that mean to whole cents using round-half-up, then annualizes the averaged cents amount at the most recent record's frequency and rounds the annual figure half-up to two decimal places. The two methods diverge whenever the same-frequency amounts are not all equal.

Finally the application's `income_eligible` flag is set true when the household's `adjunctive_program` is anything other than `NONE`, or when `annual_income_determined` is less than or equal to `income_limit`. The boundary is inclusive: an income exactly equal to the limit is eligible. Adjunctive enrollment short-circuits the income comparison entirely.

### 3.4. Nutritional Risk Assessment

Once income is determined, a CPA records the nutritional risk assessment, advancing the application from `INCOME_DETERMINED` to `RISK_ASSESSED`. The application must be in `INCOME_DETERMINED` (otherwise `ERR_INVALID_STATE`). The CPA submits the `risk_factor_codes` array; the server records those codes, computes the score and eligibility, advances the application, and increments its `version` by one.

The `total_risk_score` is the sum of severity points over the submitted codes, where each code carries fixed points: `ANEMIA` is worth 40, `UNDERWEIGHT` 35, `INADEQUATE_DIET` 20, `SHORT_STATURE` 15, `ELEVATED_LEAD` 50, and `GEST_DIABETES` 45. Two of these — `ELEVATED_LEAD` and `GEST_DIABETES` — are high-priority factors. The application's `risk_eligible` flag is set true when at least one submitted code is a high-priority factor, or when the `total_risk_score` is greater than or equal to the threshold for the participant's category. The category thresholds are 30 for `PREGNANT`, 30 for `POSTPARTUM`, 30 for `BREASTFEEDING`, 25 for `INFANT`, and 35 for `CHILD`; the boundary is inclusive, so a score exactly equal to the threshold is eligible. The presence of any high-priority factor makes the participant risk-eligible regardless of the total.

### 3.5. Approval, Denial, and the Certification Cascade

From `RISK_ASSESSED` the application forks. A CPA either approves it (advancing to `APPROVED`) or denies it (advancing to `DENIED`), and the two branches have deliberately divergent effects.

Denial is the simple branch. The application must be in `RISK_ASSESSED` (otherwise `ERR_INVALID_STATE`). On denial the application moves to `DENIED`, its `version` increments by one, no certification is created, the participant remains in `APPLICANT` status, and the agency's `active_caseload_count` is unchanged.

Approval is the consequential branch and is guarded by a sequence of business checks evaluated in the order given in Section 2.9. The application must be in `RISK_ASSESSED` (otherwise `ERR_INVALID_STATE`). First, segregation of duties: the approving CPA's `X-User-ID` must differ from the `determined_by_user_id` stamped at income determination; if they are equal, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Next, dual participation: no participant in a *different* household sharing this participant's `full_name` and `ssn_last4` may currently hold an `ACTIVE` certification; if one does, the approval is rejected with `ERR_DUAL_PARTICIPATION`. Next, the eligibility gates: the application's `income_eligible` must be true (otherwise `ERR_INCOME_INELIGIBLE`) and its `risk_eligible` must be true (otherwise `ERR_RISK_INELIGIBLE`). Finally, the caseload gate: the agency's `active_caseload_count` must be strictly less than its `caseload_cap` (otherwise `ERR_CASELOAD_EXCEEDED`).

When all checks pass, the approval stamps `certified_by_user_id` with the approving CPA's `X-User-ID`, moves the application to `APPROVED`, and triggers a three-level cascade. At the first level the server creates a `Certification` for the participant in `ACTIVE` status, recording its `participant_id` and the originating `application_id`. The certification's `period_start_utc` is set to the agency's `current_utc` at the moment of approval, and its `cert_length_days` is derived from the participant's category: 280 days for `PREGNANT`, 180 for `POSTPARTUM`, and 365 for each of `BREASTFEEDING`, `INFANT`, and `CHILD`. The `period_end_utc` is `period_start_utc` plus `cert_length_days` days and is treated as an exclusive upper bound (the period covers the start instant up to but not including the end instant). Approval also sets the participant's `priority_level` from the category: priority 1 for `PREGNANT`, `BREASTFEEDING`, and `INFANT`; priority 6 for `POSTPARTUM`; and priority 3 for `CHILD`. At the second level, creating that active certification transitions the participant from `APPLICANT` to `ACTIVE`, increments the agency's `active_caseload_count` by one, and — if the participant does not already have one — creates the participant's `EbtAccount` in `OPEN` status. The new EBT account references the `participant_id` and begins with all value counters (`issued_value_cents`, `redeemed_value_cents`, `voided_value_cents`, `remaining_value_cents`) at 0 and an empty `balance_units` map. Certifications can be listed and filtered by `participant_id` and by `application_id`.

### 3.6. The Certification Lifecycle: Suspension, Reinstatement, Expiry, and Termination

An active certification can be suspended and reinstated, forming a revision loop, and is ultimately closed by either expiry or termination. Each of these transitions propagates to the participant and the EBT account.

A CPA suspends an `ACTIVE` certification (otherwise `ERR_INVALID_STATE`), moving it to `SUSPENDED`. Suspension transitions the participant from `ACTIVE` to `SUSPENDED` and increments the participant's `version` by one, and it freezes the EBT account from `OPEN` to `FROZEN`. The agency's `active_caseload_count` is deliberately unchanged during suspension — the slot is held for the participant.

A CPA reinstates a `SUSPENDED` certification (otherwise `ERR_INVALID_STATE`), but only while the agency's `current_utc` is strictly before the certification's `period_end_utc`; a reinstatement attempted on or after the period end is rejected with `ERR_CERT_PERIOD_ENDED`. Reinstatement moves the certification back to `ACTIVE`, transitions the participant from `SUSPENDED` back to `ACTIVE` and increments the participant's `version` by one, and reopens the EBT account from `FROZEN` to `OPEN`.

Expiry is driven by a system sweep rather than by a direct request. An operator invokes the expiration sweep for an agency, and for each `ACTIVE` certification whose agency `current_utc` has reached or passed its `period_end_utc`, the certification moves to `EXPIRED`. Expiry transitions the participant from `ACTIVE` to `TERMINATED` and increments the participant's `version` by one, decrements the agency's `active_caseload_count` by one, and freezes the EBT account to `FROZEN`. The sweep reports the list of `expired_certification_ids` it processed and the `expired_count`.

Termination is the explicit closure and carries the deepest cascade. A CPA terminates a certification that is in `ACTIVE` or in `SUSPENDED` (any other state yields `ERR_INVALID_STATE`); both starting states run the identical cascade. At the first level the certification moves to `TERMINATED`, the participant moves to `TERMINATED`, the participant's `version` increments by one, and the agency's `active_caseload_count` is decremented by one, compensating the debit that approval applied. At the second level, every food prescription on this certification whose status is `ISSUED` or `REDEEMED_PARTIAL` is moved to `VOIDED`. At the third level, each voided prescription moves its remaining unredeemed value into the EBT account's `voided_value_cents`, zeroes the corresponding `balance_units`, and the EBT account recomputes its `remaining_value_cents`; the EBT account is then frozen to `FROZEN`. (The same downstream voiding-and-freeze cascade is what expiry triggers on the prescriptions and EBT account belonging to an expired certification.)

### 3.7. Food Prescriptions and the EBT Top-Up

With an active certification in hand, a CPA issues a food package by creating a `FoodPrescription`. The request carries the `certification_id`, a `line_items` array of `{food_category, requested_units}` entries, an optional `issuance_mode` (defaulting to `FULL`, the alternative being `PRORATED`), and — because issuance is OCC-guarded against the participant — the `expected_participant_version` described in Section 2.7. On creation the server denormalizes the certification's participant onto the prescription's `participant_id`, the prescription begins in `ISSUED` status, the computed `prescribed_value_cents` is set, and the participant's `version` is incremented by one. Food prescriptions can be listed and filtered by `certification_id` and by `participant_id`.

For each line item the server first looks up the per-category cap for the participant's WIC category. The cap table is category-specific. A `PREGNANT` participant may receive up to 4 `MILK`, 2 `EGGS`, 2 `JUICE`, 3 `CEREAL`, and 11 `FRUIT_VEG`. A `POSTPARTUM` participant may receive up to 4 `MILK`, 2 `EGGS`, 2 `JUICE`, 3 `CEREAL`, and 9 `FRUIT_VEG`. A `BREASTFEEDING` participant may receive up to 6 `MILK`, 2 `EGGS`, 2 `JUICE`, 4 `CEREAL`, and 11 `FRUIT_VEG`. An `INFANT` may receive up to 9 `INFANT_FORMULA`, 24 `INFANT_CEREAL`, and 8 `FRUIT_VEG`. A `CHILD` may receive up to 4 `MILK`, 1 `EGGS`, 2 `JUICE`, 4 `CEREAL`, and 8 `FRUIT_VEG`. If a line item names a `food_category` for which the participant's category has no cap, the issuance is rejected with `ERR_CATEGORY_FOOD_MISMATCH`.

The number of units actually issued for a line item is the smaller of the requested units and that category cap. Under `FULL` issuance the issued units equal that capped number directly. Under `PRORATED` issuance the issued units are prorated by how much of the issuance month remains: the server computes the number of days in the calendar month of the agency's `current_utc`, computes the days remaining as that month length minus the day-of-month of `current_utc` plus one (inclusive of the current day), forms the factor as days-remaining divided by days-in-month, multiplies the capped units by that factor, and floors the result to a whole number of units. The rounding order is pinned: under proration the per-item floor is applied *before* pricing, and only then are the item values summed — proration never sums first and rounds afterward.

Each line item's value is its issued units multiplied by the per-unit price for the food category, in cents: `MILK` 350, `EGGS` 300, `JUICE` 250, `CEREAL` 400, `FRUIT_VEG` 200, `INFANT_FORMULA` 1200, and `INFANT_CEREAL` 300. The prescription's `prescribed_value_cents` is the sum of the per-item values across all line items, computed in integer cents with no rounding applied after the summation. Issuing the prescription tops up the participant's `EbtAccount`: the prescribed value is added to the account's `issued_value_cents`, the issued units are added to the per-category `balance_units` map, and the account's `remaining_value_cents` is recomputed.

### 3.8. EBT Reconciliation and Redemptions

The `EbtAccount` is the conserved-quantity ledger for a participant's benefits. It carries a `balance_units` map from food category to remaining issued units, and four cents totals: `issued_value_cents` is the cumulative value of all units issued onto the account across food prescriptions; `redeemed_value_cents` is the cumulative value of redeemed units drawn down in chronological order; `voided_value_cents` is the cumulative value moved out when prescriptions are voided; and `remaining_value_cents` equals `issued_value_cents` minus `redeemed_value_cents` minus `voided_value_cents`. The conserved-quantity invariant the ledger always maintains is that `remaining_value_cents` equals the sum, over each food category, of that category's remaining `balance_units` multiplied by the category's per-unit price; `remaining_value_cents` is never negative. EBT accounts can be listed and filtered by `participant_id`, and a participant may read only their own account.

A redemption is recorded by a participant (or by a clerk acting on the participant's behalf) by creating a `Redemption` that carries the `ebt_account_id`, the `vendor_id` of the authorized vendor where the purchase occurred, the `food_category` being drawn down, and the positive integer `units` redeemed. The server assigns each redemption a `sequence_index` in creation order within the EBT account, starting at 0; this sequence index — never the record's `id` — pins the chronological replay order for reconciliation. The redemption's `value_cents` is computed as the units multiplied by the per-unit price for the food category.

A redemption is gated by several cross-entity conditions, each checked before the draw-down is applied. The certification owning the prescription being drawn against must be in `ACTIVE` status, otherwise the redemption is rejected with `ERR_CERT_NOT_ACTIVE`. The EBT account must be in `OPEN` status, otherwise `ERR_EBT_FROZEN`. The referenced vendor must exist and be in `AUTHORIZED` status, otherwise `ERR_VENDOR_NOT_AUTHORIZED`. And the redeemed `units` must not exceed the remaining `balance_units` for that `food_category`, otherwise `ERR_INSUFFICIENT_BALANCE`. When the redemption succeeds the server appends the redemption event, debits the `balance_units` for the category, adds the redemption value to the account's `redeemed_value_cents`, and recomputes `remaining_value_cents`.

A redemption also advances the food prescription it draws against. A prescription begins in `ISSUED`. The first redemption that still leaves some prescribed units remaining moves the prescription to `REDEEMED_PARTIAL`; the redemption that drains the last remaining unit moves it to `REDEEMED_FULL`. Both of these draw-down transitions are subject to the same four gates above (active certification, open account, authorized vendor, sufficient balance).

### 3.9. Vendor Authorization and Compliance

Vendors progress through their own lifecycle, managed by a clerk, that includes a cyclic suspend-and-reinstate loop. A `PENDING` vendor is authorized — moving to `AUTHORIZED` — only from `PENDING` (otherwise `ERR_INVALID_STATE`). Only an `AUTHORIZED` vendor may back redemptions, which is why the redemption check above demands `AUTHORIZED` status.

Compliance violations are recorded against an `AUTHORIZED` vendor by submitting a `points` amount, which is added to the vendor's accumulated `violation_points`. When the cumulative `violation_points` reaches or exceeds the suspension threshold of 100, the vendor is automatically moved from `AUTHORIZED` to `SUSPENDED`; the boundary is inclusive, so exactly 100 points triggers suspension. A suspended vendor can no longer back redemptions. Recording a violation requires the vendor to be in `AUTHORIZED` status (otherwise `ERR_INVALID_STATE`).

A `SUSPENDED` vendor is reinstated by a clerk back to `AUTHORIZED`, and reinstatement resets the vendor's `violation_points` to 0 (the reinstate transition requires `SUSPENDED` status, otherwise `ERR_INVALID_STATE`). A vendor in either `AUTHORIZED` or `SUSPENDED` status can be terminated, moving it permanently to `TERMINATED` (any other starting state yields `ERR_INVALID_STATE`); termination is final. Vendors can be listed and filtered by `agency_id`.

### 3.10. Clinic Appointments

Clinic appointments are scheduled by a clerk against a clinic. Scheduling carries the `clinic_id`, the `participant_id` of the participant being seen, a `purpose` of `INITIAL_CERT`, `RECERT`, `NUTRITION_ED`, or `BF_SUPPORT`, the `start_utc` (inclusive) and `end_utc` (exclusive) bounding the appointment as a half-open interval, and the `expected_clinic_version` for the OCC check in Section 2.7. A new appointment begins in `SCHEDULED` status, and scheduling increments the clinic's `version` by one.

Scheduling and rescheduling are both overlap-checked on the clinic. The candidate interval is `[start_utc, end_utc)`. For each existing appointment on the *same* `clinic_id` that is currently in `SCHEDULED` or `RESCHEDULED` status, the candidate collides if the candidate's start is before the existing appointment's end and the existing appointment's start is before the candidate's end. The comparison is strict, so two intervals that merely touch at an endpoint — the candidate's start equal to an existing end, or the candidate's end equal to an existing start — do not collide and are allowed. A collision is rejected with `ERR_APPOINTMENT_OVERLAP`. (Where a clinic defines a non-zero `appointment_buffer_minutes`, that buffer is the gap it enforces between appointments; a buffer of 0 permits back-to-back booking.)

A clerk reschedules a `SCHEDULED` appointment by supplying a new `start_utc` and `end_utc`; the appointment must be in `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and the new interval must clear the same overlap check (otherwise `ERR_APPOINTMENT_OVERLAP`). Rescheduling updates the interval and moves the appointment to `RESCHEDULED`. A clerk then confirms a `RESCHEDULED` appointment (otherwise `ERR_INVALID_STATE`), moving it back to `SCHEDULED`.

A CPA completes a `SCHEDULED` appointment (otherwise `ERR_INVALID_STATE`), but only when the participant being seen is currently in `APPLICANT` or `ACTIVE` status; a participant in any other status causes the completion to be rejected with `ERR_PARTICIPANT_NOT_SERVICEABLE`. Completion moves the appointment to `COMPLETED`. A clerk marks a `SCHEDULED` appointment as a no-show — moving it to `NO_SHOW` — but only once it is in the past, meaning the agency's `current_utc` has reached or passed the appointment's `end_utc`; an attempt before that point is rejected with `ERR_APPOINTMENT_NOT_PAST`. A clerk cancels an appointment that is in `SCHEDULED` or `RESCHEDULED` status (otherwise `ERR_INVALID_STATE`), moving it to `CANCELLED` and freeing the interval. Appointments can be listed and filtered by `clinic_id` and by `participant_id`.

### 3.11. Breastfeeding Peer-Support Sessions

A CPA schedules a breastfeeding peer-support session for a participant by supplying the `participant_id`, the opaque `peer_counselor_id` of the counselor leading the session, and the `start_utc` and `end_utc` bounding it. A new session begins in `SCHEDULED` status. Sessions can be listed and filtered by `participant_id`.

Peer-session scheduling is collision-checked on the counselor using a different interval semantics from clinic appointments — a buffer-based adjacency rather than half-open arithmetic. The candidate session interval is treated as closed, `[start_utc, end_utc]`. For each existing session on the *same* `peer_counselor_id` currently in `SCHEDULED` status, the server computes the gap in minutes between the two intervals (zero if they overlap at all), and the candidate collides if that gap is strictly less than the 15-minute travel buffer; a gap of exactly 15 minutes is allowed. A collision is rejected with `ERR_APPOINTMENT_OVERLAP`. A CPA completes a `SCHEDULED` session, moving it to `COMPLETED`, or cancels a `SCHEDULED` session, moving it to `CANCELLED` and freeing the buffered interval; either transition requires the session to be in `SCHEDULED` (otherwise `ERR_INVALID_STATE`).

### 3.12. Operator Clock and Expiration Sweep

Two operator capabilities, available to both staff roles for test-driving and operations, manipulate the deterministic agency clock and drive time-based transitions. The first sets an agency's clock: the request supplies the target `agency_id` and the `to_iso8601` instant, and the server assigns that instant to the agency's `current_utc`. The second is the expiration sweep introduced in Section 3.6: for the supplied `agency_id`, it expires every `ACTIVE` certification whose `period_end_utc` the agency's `current_utc` has reached or passed, running the participant-termination, caseload-decrement, prescription-voiding, and EBT-freeze cascade for each, and returns `expired_certification_ids` and `expired_count`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including the lifecycle transitions and the operator clock capabilities — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set an agency's deterministic clock | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/_clock/advance-expirations` | Sweep and expire due certifications for an agency | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/agencies` | Create a local WIC agency | EligibilityClerk |
| GET | `/agencies/{id}` | Get an agency | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/clinics` | Create a clinic site | EligibilityClerk |
| GET | `/clinics/{id}` | Get a clinic | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/clinics` | List clinics (filter by agency_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/vendors` | Register a food vendor | EligibilityClerk |
| GET | `/vendors/{id}` | Get a vendor | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/vendors` | List vendors (filter by agency_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/vendors/{id}/authorize` | Authorize a pending vendor | EligibilityClerk |
| POST | `/vendors/{id}/record-violation` | Record violation points; may auto-suspend | EligibilityClerk |
| POST | `/vendors/{id}/reinstate` | Reinstate a suspended vendor | EligibilityClerk |
| POST | `/vendors/{id}/terminate` | Terminate a vendor | EligibilityClerk |
| POST | `/households` | Create a household economic unit | EligibilityClerk |
| GET | `/households/{id}` | Get a household | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/households` | List households (filter by agency_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/participants` | Create a participant | EligibilityClerk |
| GET | `/participants/{id}` | Get a participant | EligibilityClerk, CompetentProfessionalAuthority, Participant |
| GET | `/participants` | List participants (filter by household_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/applications` | Open a certification application | EligibilityClerk |
| GET | `/applications/{id}` | Get an application | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/applications` | List applications (filter by participant_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/income-records` | Attach an income record to an application | EligibilityClerk |
| GET | `/income-records/{id}` | Get an income record | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/income-records` | List income records (filter by application_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/applications/{id}/determine-income` | Run income determination | EligibilityClerk |
| POST | `/applications/{id}/assess-risk` | Record the nutritional risk assessment | CompetentProfessionalAuthority |
| POST | `/applications/{id}/approve` | Approve and certify; cascades certification creation | CompetentProfessionalAuthority |
| POST | `/applications/{id}/deny` | Deny; no certification created | CompetentProfessionalAuthority |
| GET | `/certifications/{id}` | Get a certification | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/certifications` | List certifications (filter by participant_id, application_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/certifications/{id}/suspend` | Suspend an active certification | CompetentProfessionalAuthority |
| POST | `/certifications/{id}/reinstate` | Reinstate a suspended certification | CompetentProfessionalAuthority |
| POST | `/certifications/{id}/terminate` | Terminate a certification; cascades to prescriptions and EBT | CompetentProfessionalAuthority |
| POST | `/food-prescriptions` | Issue a food package onto the participant's EBT | CompetentProfessionalAuthority |
| GET | `/food-prescriptions/{id}` | Get a food prescription | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/food-prescriptions` | List food prescriptions (filter by certification_id, participant_id) | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/ebt-accounts/{id}` | Get an EBT account | EligibilityClerk, CompetentProfessionalAuthority, Participant |
| GET | `/ebt-accounts` | List EBT accounts (filter by participant_id) | EligibilityClerk, CompetentProfessionalAuthority, Participant |
| POST | `/redemptions` | Record an EBT redemption | Participant, EligibilityClerk |
| GET | `/redemptions/{id}` | Get a redemption | EligibilityClerk, CompetentProfessionalAuthority, Participant |
| GET | `/redemptions` | List redemptions (filter by ebt_account_id, vendor_id) | EligibilityClerk, CompetentProfessionalAuthority, Participant |
| POST | `/clinic-appointments` | Schedule a clinic appointment | EligibilityClerk |
| GET | `/clinic-appointments/{id}` | Get a clinic appointment | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/clinic-appointments` | List appointments (filter by clinic_id, participant_id) | EligibilityClerk, CompetentProfessionalAuthority |
| PATCH | `/clinic-appointments/{id}` | Reschedule an appointment | EligibilityClerk |
| POST | `/clinic-appointments/{id}/confirm` | Confirm a rescheduled appointment | EligibilityClerk |
| POST | `/clinic-appointments/{id}/complete` | Complete an appointment | CompetentProfessionalAuthority |
| POST | `/clinic-appointments/{id}/no-show` | Mark a past appointment as no-show | EligibilityClerk |
| POST | `/clinic-appointments/{id}/cancel` | Cancel an appointment | EligibilityClerk |
| POST | `/peer-sessions` | Schedule a breastfeeding peer-support session | CompetentProfessionalAuthority |
| GET | `/peer-sessions/{id}` | Get a peer-support session | EligibilityClerk, CompetentProfessionalAuthority |
| GET | `/peer-sessions` | List peer-support sessions (filter by participant_id) | EligibilityClerk, CompetentProfessionalAuthority |
| POST | `/peer-sessions/{id}/complete` | Complete a peer-support session | CompetentProfessionalAuthority |
| POST | `/peer-sessions/{id}/cancel` | Cancel a peer-support session | CompetentProfessionalAuthority |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_INCOME_RECORDS` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUAL_PARTICIPATION` | 409 |
| `ERR_INCOME_INELIGIBLE` | 409 |
| `ERR_RISK_INELIGIBLE` | 409 |
| `ERR_CASELOAD_EXCEEDED` | 409 |
| `ERR_CERT_NOT_ACTIVE` | 409 |
| `ERR_EBT_FROZEN` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 409 |
| `ERR_VENDOR_NOT_AUTHORIZED` | 409 |
| `ERR_CERT_PERIOD_ENDED` | 409 |
| `ERR_APPOINTMENT_OVERLAP` | 409 |
| `ERR_APPOINTMENT_NOT_PAST` | 409 |
| `ERR_PARTICIPANT_NOT_SERVICEABLE` | 409 |
| `ERR_CATEGORY_FOOD_MISMATCH` | 409 |
