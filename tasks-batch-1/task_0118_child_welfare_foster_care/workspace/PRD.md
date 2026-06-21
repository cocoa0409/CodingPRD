# Child Welfare & Foster Care API — Product Requirements Document

## 1. Introduction

This document specifies the backend service that carries a child-welfare agency's casework from the moment a hotline call is received through to a child's permanent placement or emancipation. The domain is unforgiving: a single intake decision can put a child into state custody, and statutory clocks begin running the instant a child is removed from home. The service therefore models the entire pipeline — hotline intake and screening, abuse/neglect investigation and safety assessment, removal and placement into a licensed foster home, foster-home licensing and household background checks, the court-supervised case plan with its mandated parent-child visitation, the docket of dependency hearings, and the permanency outcome (reunification, adoption, or another planned permanent living arrangement) — as a connected graph of resources rather than a set of isolated records.

Two themes shape every requirement below. First, **segregation of duties**: the worker who screens a referral into the system must never be the same worker who investigates it, and licensing, casework, and judicial authority are each held by distinct roles. Second, **immediate, cascading consistency**: suspending a foster home must instantly remove the children placed there; closing a case must instantly mark its child permanent; placing the first child on a case must instantly start the federal permanency clock. The API is the single source of truth for these cascades, and the rules that govern them are described in prose throughout this document — they are not optional conveniences but the core correctness contract a conforming implementation must satisfy.

A note on time. Because the benchmark must exercise statutory timeframes (license terms measured in days, the months-a-child-has-been-in-care clock, visitation windows) deterministically, the service maintains a **logical system clock** that an operator sets explicitly: an `Admin`-only capability accepts a single `to_iso8601` instant and fixes the logical UTC clock to that value, so every subsequent computed clock reads it. Every "current clock", "now", or elapsed-time computation in this document reads that logical clock, never the wall clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are well-formed but the named role is not permitted to invoke the requested operation (per the authorization matrix in Section 4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows: `Admin`, `IntakeScreener`, `Investigator`, `Caseworker`, `LicensingWorker`, and `Judge`.

Four of these roles are **entity-backed by a `Caseworker` record**, meaning `X-User-ID` is the `id` of an actual persisted `Caseworker`:

- When `X-User-Role` is `IntakeScreener`, `X-User-ID` is the `id` of the acting `Caseworker`; ownership checks compare a referenced `Caseworker` foreign key to `X-User-ID`. In particular, when a screener screens a referral in, the referral's `screened_in_by` is set to this `X-User-ID`.
- When `X-User-Role` is `Investigator`, `X-User-ID` is the `id` of the acting `Caseworker`; an investigation may only be started or decided by the worker whose `id` equals the investigation's `investigator_id`.
- When `X-User-Role` is `Caseworker`, `X-User-ID` is the `id` of the acting `Caseworker` who owns dependency casework.
- When `X-User-Role` is `LicensingWorker`, `X-User-ID` is the `id` of the acting `Caseworker`; this is the worker who owns a foster home's license, recorded as `licensing_worker_id` on the home.

The remaining two roles are **opaque operator identifiers** not tied to any persisted entity:

- When `X-User-Role` is `Admin`, `X-User-ID` is an opaque platform-operator identifier. The server does not compare it to any entity's `id`; the `Admin` registers caseworkers, advances the logical clock, and runs system sweeps.
- When `X-User-Role` is `Judge`, `X-User-ID` is an opaque judicial-officer identifier. The server does not compare it to any entity's `id`; the `Judge` presides over the hearing docket and records rulings.

The four entity-backed roles (`IntakeScreener`, `Investigator`, `Caseworker`, `LicensingWorker`) correspond to the four values of a `Caseworker` record's `role_type` field — `SCREENER`, `INVESTIGATOR`, `CASEWORKER`, and `LICENSING` respectively — and a worker may only be assigned work matching the segregated duty their `role_type` names.

A `Caseworker` record is registered by the `Admin` with the worker's legal `full_name`, their `role_type` from the four values above, a login `email` that must be unique across all caseworker rows, and an `active` flag (defaulting to true) governing whether the worker may be assigned new work. An inactive worker — `active` set to false — is not eligible for new assignments.

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and represents the number of leading records to skip. A `limit` or `offset` outside its permitted range is a malformed request.

List results are always returned in ascending order of `created_at` — that is, oldest first. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when records remain beyond the returned page).

Across every endpoint, a request body that is structurally malformed — a required field absent, a field of the wrong type, or an enum field carrying a value outside its permitted set — is rejected with `ERR_INVALID_REQUEST` (HTTP 422). This basic shape validation is the lowest-priority of the constraint checks, applied only after the authentication, authorization, existence, and state guards above have passed; it is distinct from the numeric-range validation that yields `ERR_VALIDATION_LIMIT` for values such as a `bed_capacity` below 1, a `protective_capacity` outside 0 to 10, or an `objectives_total` below 1.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits, set once at creation and never changed.

Every entity in this system also carries an `updated_at` timestamp (same ISO 8601 UTC format) and an integer `version`. The `version` of a freshly created resource is its initial value, and **every mutation of a resource increments that resource's `version` by exactly one and refreshes its `updated_at` to the current clock**. When this document says an operation "bumps the version" of an entity, it means precisely this: increment by one and refresh `updated_at`. All entities in this system — `Caseworker`, `Referral`, `Investigation`, `Case`, `Child`, `FosterHome`, `CaregiverScreening`, `Placement`, `CasePlan`, `Visitation`, and `Hearing` — carry `updated_at` and `version`.

### 2.5. Cascading Consistency Across the Resource Graph

Many operations mutate more than one resource. Whenever an operation changes a child's placement status, the status of the placement, the case, and the foster home may all move together, and each entity that changes has its `version` bumped and its `updated_at` refreshed independently. The detailed cascades — what disrupting a placement does to the child and the home, what suspending a home does to every child it holds, what closing a case does to the child — are described where the relevant workflow lives in Section 3. The governing principle here is that these cascades are synchronous and complete within the single request that triggers them; a reader must never observe a half-applied cascade.

### 2.6. Nested Resource Resolution

Several operations name a resource by a path identifier and additionally reference resources by foreign key in the request body. Existence is validated **left to right**: any resource named in the URL path is resolved first, and only then are body-referenced resources resolved. The first reference that resolves to nothing yields `ERR_NOT_FOUND` (HTTP 404). This ordering matters when, for example, a placement request names both a `child_id` and a `foster_home_id`; the path-level resource (if any) is checked before either body reference.

### 2.7. Numeric Precision and Rounding

Most computed quantities in this system are integers: screening scores, safety scores, match scores, ages in years, and months in care are all whole numbers. Where a calculation produces a fractional intermediate, that intermediate is carried with full precision and only the final stored value is reduced to its declared form. The sole non-integer computed quantity is a case plan's `compliance_pct`, which is expressed to **two decimal places using round-half-up** (a value whose third decimal is five or greater rounds the second decimal up).

### 2.8. Optimistic Concurrency on Foster Homes

Two operations are guarded by optimistic concurrency control, and both guard against a stale view of a **`FosterHome`**. In each case the request body must carry `expected_foster_home_version`, the `version` the client last observed on the target home, and the operation proceeds only if that value equals the home's current `version`. If it does not match — because another writer has advanced the home's `version` since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The first guarded operation is **creating a placement**. A placement-create request must carry `expected_foster_home_version` equal to the target home's current `version`. If another writer has already consumed the home's last open bed (a prior placement that legitimately advanced the home's `version` and filled capacity), the requesting client's view of the home's remaining beds is stale, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overbooking the home.

The second guarded operation is **issuing a full license**. A full-license request must carry `expected_foster_home_version` equal to the target home's current `version`. If another writer has added or cleared a `CaregiverScreening` since the client last read the home (which bumps the home's `version`), the licensing decision would rest on a stale clearance picture, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other operation accepts a version field.

### 2.9. Common Resource Properties Summary

For clarity, the resources whose lifecycles drive this system are: the `Caseworker` (a staff member), the `Referral` (a hotline intake), the `Investigation` (a fact-finding episode), the `Case` (a dependency matter), the `Child` (the subject of care), the `FosterHome` (a licensed placement resource), the `CaregiverScreening` (a household background check), the `Placement` (a child-in-a-bed episode), the `CasePlan` (the reunification roadmap), the `Visitation` (a scheduled parent-child visit), and the `Hearing` (a court appearance). Each section of the business logic below names the fields these resources carry as they are used.

## 3. Business Logic & Workflows

### 3.1. Hotline Intake and Screening

A child-welfare episode begins when a hotline call arrives and an `IntakeScreener` records a `Referral`. The screener supplies who is calling via `reporter_type` (one of `MANDATED`, `ANONYMOUS`, `RELATIVE`, or `SELF`), the alleged victim's name as `child_name`, the primary `alleged_maltreatment` (one of `PHYSICAL_ABUSE`, `SEXUAL_ABUSE`, `NEGLECT`, or `EMOTIONAL_ABUSE`), and an optional list of present-danger `priority_factors`, each drawn from the set `PRIOR_REPORT`, `CAREGIVER_SUBSTANCE`, `INJURY_VISIBLE`, `AGE_UNDER_3`, and `NO_CAREGIVER`. A new referral is born in status `RECEIVED`. Its `response_priority`, `screening_score`, `screened_in_by`, and `linked_case_id` are all null at this point.

Screening is the decisive fork. When a screener screens a `RECEIVED` referral, the system computes a weighted intake risk score and, on the basis of that score, either advances the referral to `SCREENED_IN` (a worker must investigate) or to `SCREENED_OUT` (terminal — no investigation will follow). Both branches first compute and store the `screening_score` and derive `response_priority` from it; the screen of a referral not in `RECEIVED` status is an invalid transition (`ERR_INVALID_STATE`).

The **intake risk score** is assembled as follows. Start from a base weight determined by the alleged maltreatment type: `SEXUAL_ABUSE` contributes 50, `PHYSICAL_ABUSE` contributes 40, `NEGLECT` contributes 25, and `EMOTIONAL_ABUSE` contributes 20. To that base, add a factor sum: for each distinct danger factor present in `priority_factors`, add its weight — `PRIOR_REPORT` adds 10, `CAREGIVER_SUBSTANCE` adds 12, `INJURY_VISIBLE` adds 15, `AGE_UNDER_3` adds 18, and `NO_CAREGIVER` adds 30 — counting each factor only once even if it appears more than once. Then add a reporter bonus keyed on `reporter_type`: `MANDATED` adds 8, `RELATIVE` adds 4, `SELF` adds 2, and `ANONYMOUS` adds nothing. The raw total is the sum of base, factor sum, and reporter bonus. The stored `screening_score` is that raw total **capped at a ceiling of 100** — if the raw total exceeds 100, the score is 100; the cap is applied only after the full summation, never to the individual terms.

The screen-in decision and the `response_priority` band both read the **capped** score. A referral is screened in when its `screening_score` is at least 45; otherwise it is screened out. The response-timeframe band is then: a score of at least 75 yields `P1_24H`; a score of at least 45 but below 75 yields `P2_72H`; and a score below 45 yields `P3_10D`. By construction, every screened-out referral carries `P3_10D`, and every screened-in referral carries either `P1_24H` or `P2_72H`. On the screen-in branch the system additionally records `screened_in_by` as the acting screener's `X-User-ID`; on the screen-out branch `screened_in_by` remains null. Either branch bumps the referral's `version`.

Later in the lifecycle, when a dependency case is opened from this referral's investigation, the referral makes a final, system-driven transition from `SCREENED_IN` to `LINKED`: the system writes the new case's `id` into the referral's `linked_case_id` and bumps the referral's `version`. This "bubble-up" is the only way a referral reaches `LINKED`, and it is covered with the case-opening workflow in Section 3.3.

### 3.2. Investigation and Safety Assessment

A `Caseworker` opens an `Investigation` on a screened-in referral, supplying the `referral_id` of the referral under investigation and the `investigator_id` of the assigned `Investigator`. Optionally the caseworker may pre-record `safety_factors` and a `protective_capacity` rating at open time, though these are normally captured at the decision step. A new investigation is born in status `ASSIGNED`.

Two gates apply at open time. The referral must actually be screened in: opening an investigation against a referral whose `status` is anything other than `SCREENED_IN` is rejected with `ERR_REFERRAL_NOT_SCREENED_IN`. And the **segregation-of-duties** rule must hold: the supplied `investigator_id` must not equal the originating referral's `screened_in_by`. A worker may not investigate a referral they themselves screened in; that conflict is rejected with `ERR_SOD_CONFLICT`.

The assigned `Investigator` then begins the home visit, moving the investigation from `ASSIGNED` to `IN_PROGRESS`. Only the worker whose `id` equals the investigation's `investigator_id` may do this; an attempt from any other identity, or against an investigation not in `ASSIGNED`, fails the state guard. Starting bumps the investigation's `version`.

When the investigator records the safety decision, they supply the confirmed `safety_factors` (a set drawn from `NO_FOOD`, `VIOLENCE_PRESENT`, `SUPERVISION_ABSENT`, `MEDICAL_NEGLECT`, `DRUG_ENV`, and `UNSAFE_SLEEP`) together with the caregiver's `protective_capacity` rating, an integer from 0 to 10 inclusive. The system computes a **safety decision score** and, on its value, branches the investigation to `SAFE`, `CONDITIONALLY_SAFE`, or `UNSAFE`. The decision may only be recorded from `IN_PROGRESS`.

The safety decision score is computed in a fixed three-step order. **Step one — danger.** Sum the weight of each distinct confirmed safety factor: `NO_FOOD` weighs 25, `VIOLENCE_PRESENT` weighs 35, `SUPERVISION_ABSENT` weighs 30, `MEDICAL_NEGLECT` weighs 28, `DRUG_ENV` weighs 22, and `UNSAFE_SLEEP` weighs 18; this total is the danger value. **Step two — protective credit.** The caregiver's protective capacity offsets danger, but the credit is capped: the credit equals the smaller of the danger value and the product of `protective_capacity` and six, so the credit can never exceed danger. The net is the danger value minus the credit, floored at zero (never negative). **Step three — present-danger override.** If the confirmed `safety_factors` include `VIOLENCE_PRESENT` or `SUPERVISION_ABSENT`, the safety decision score is the larger of the net and 70, forcing the result into the removal band; otherwise the safety decision score is simply the net. This three-step order — credit, then floored net, then override — is load-bearing and must be evaluated exactly as stated.

The stored `safety_decision_score` then selects the branch. A score of at least 70 yields `UNSAFE` and sets `removal_recommended` to true (the present-danger override therefore always lands here). A score of at least 40 but below 70 yields `CONDITIONALLY_SAFE` and sets `removal_recommended` to false — the child stays in the home under an in-home safety plan. A score below 40 yields `SAFE`, sets `removal_recommended` to false, and opens no case. Whichever branch fires, the investigation's `version` is bumped. The fields `safety_decision_score` and `removal_recommended` are null until this decision is recorded.

### 3.3. Opening a Dependency Case and Registering the Child

A dependency `Case` may be opened only from an investigation that recommended state intervention — that is, an investigation whose status is `UNSAFE` or `CONDITIONALLY_SAFE`. The caseworker supplies the `investigation_id`; opening against an investigation in any other status (including `SAFE`) is rejected with `ERR_INVESTIGATION_NOT_REMOVAL`. A new case is born in status `OPEN` with `permanency_goal` defaulting to `REUNIFICATION`. Its `removal_date` is null (no child has yet been removed into care), its computed `months_in_care` is 0, and `tpr_clock_breached` is false.

Opening the case triggers the bubble-up described in Section 3.1: the system sets the originating `Referral`'s `linked_case_id` to the new case's `id` and transitions that referral from `SCREENED_IN` to `LINKED`, bumping the referral's `version`. The link from case back to its origin is the `investigation_id` carried on the case; the referral is reached through that investigation's `referral_id`.

Once a case is open, the caseworker registers each `Child` on it, supplying the `case_id` the child belongs to, the child's `full_name`, and `date_of_birth` (a UTC date that drives both age and aging-out eligibility). A new child is born in status `IN_HOME` with `current_placement_id` null. The child's `age_years` — whole years elapsed from `date_of_birth` to the current clock — is recomputed whenever the child is read.

### 3.4. Foster-Home Licensing and Caregiver Background Checks

In parallel with casework, a `LicensingWorker` builds out the supply of placement resources. The worker registers a `FosterHome` with its owning `licensing_worker_id`, a `home_name`, a `bed_capacity` (the maximum number of children that may hold an active bed at once, which must be at least 1), a `max_age_years` (the oldest child age the home is licensed to accept, an integer from 0 to 21 inclusive), and the list of `accepts_maltreatment` categories (a subset of `PHYSICAL_ABUSE`, `SEXUAL_ABUSE`, `NEGLECT`, `EMOTIONAL_ABUSE`) the home will take matched children for. A new home is born with `license_status` `PENDING` and `license_expires_at` null. Its computed `active_placement_count` (placements currently in `ACTIVE` state) and `clearances_complete` flag are derived on read. A `bed_capacity` below 1 or a `max_age_years` outside 0 to 21 is rejected with `ERR_VALIDATION_LIMIT`.

Each adult household member must clear a background check. The worker adds a `CaregiverScreening` to a home, supplying the `foster_home_id` it belongs to, the `member_name`, and an optional `disqualifying` flag (default false) indicating whether the returned record contains a disqualifying offense. A new screening is born `PENDING`. Resolving a pending screening drives it to one of two terminal states: a clean record (`disqualifying` is false) clears to `CLEARED`; a disqualifying record (`disqualifying` is true) flags to `FLAGGED`. Either resolution recomputes the owning home's `clearances_complete` and bumps the screening's `version`. The home's `clearances_complete` is true only when every one of its `CaregiverScreening` rows is `CLEARED`; while any screening remains `PENDING` or `FLAGGED`, it is false.

Licensing a home has two paths. The **full-license** path moves the home from `PENDING` (or up from `PROVISIONAL`) to `LICENSED`, but only when `clearances_complete` is true — every screening cleared. Two prerequisite failures are distinguished: if any screening is `FLAGGED`, the request is rejected with `ERR_CLEARANCE_FLAGGED`; if no screening is flagged but at least one is still `PENDING`, it is rejected with `ERR_CLEARANCES_INCOMPLETE`. The full-license request is also optimistic-concurrency-guarded on the home and carries `expected_foster_home_version` (see Section 2.8). On success it sets `license_expires_at` to the current clock plus 365 days and bumps the home's `version`.

The **provisional-license** path lets a home accept placements before all clearances return. It moves a `PENDING` home to `PROVISIONAL`, and is permitted only when at least one `CaregiverScreening` is still `PENDING` and none is `FLAGGED` — a flagged screening blocks even a provisional license (`ERR_CLEARANCE_FLAGGED`). On success it sets `license_expires_at` to the current clock plus 90 days and bumps the `version`. A provisional home later earns a full license by the full-license path once every screening clears.

A `LICENSED` home may be **suspended** by its licensing authority, and a `SUSPENDED` home may be **reinstated** back to `LICENSED` (reinstatement requires `clearances_complete` to be true, and a `FLAGGED` screening blocks it with `ERR_CLEARANCE_FLAGGED`). Reinstatement resets `license_expires_at` to the current clock plus 365 days and bumps the `version`. The cascade that suspension and license lapse trigger on the children placed in the home is described in Section 3.7.

### 3.5. Placing a Child and Computing the Match

Placement is where the child aggregate and the foster-home aggregate meet. A caseworker creates a `Placement` by supplying the `child_id` to be placed, the `foster_home_id` holding the bed, and `expected_foster_home_version` for the concurrency guard. The placement's own `case_id` is copied from the child's case at creation; its `start_at` is set to the current clock; `end_at` is null while the placement is `ACTIVE`; and its `match_score` is computed and recorded at creation. A new placement is born `ACTIVE`.

Several gates protect a placement create, and their relative priority matters because more than one can be violated at once. After authentication, authorization, and existence of the named child and home are confirmed (the home and child must exist or the request is `ERR_NOT_FOUND`), the checks proceed in this order: the home must be in a state that accepts children — its `license_status` must be `LICENSED` or `PROVISIONAL`, never `PENDING`, `SUSPENDED`, or `EXPIRED`, else `ERR_HOME_NOT_LICENSED`; the child's `age_years` must be no greater than the home's `max_age_years`, else `ERR_AGE_NOT_LICENSED`; the home must have an open bed — its `active_placement_count` must be strictly less than its `bed_capacity`, else `ERR_NO_BEDS`; and finally the optimistic-concurrency check, where `expected_foster_home_version` must equal the home's current `version`, else `ERR_STALE_VERSION`. A request that violates several of these surfaces the earliest in this ordering.

The **match score** is computed at creation, in a fixed step order, against the home's state **as it stands before this placement consumes a bed**. First, read the home's headroom as its `bed_capacity` minus its current `active_placement_count` — this read happens strictly before the new bed is taken, so headroom reflects the pre-placement count. Second, compute an age-fit credit: take the gap between the home's `max_age_years` and the child's `age_years`, multiply that gap by 4, and clamp the result to lie between 0 and 40 inclusive (negative gaps yield 0, and the credit never exceeds 40). Third, compute a maltreatment-fit credit: if the case's originating maltreatment is among the home's `accepts_maltreatment`, the credit is 30; otherwise it is 0. Fourth, compute a capacity-fit credit: take the smaller of the headroom and 3, then multiply by 10. The `match_score` is the sum of the age-fit, maltreatment-fit, and capacity-fit credits. The match score is advisory — a home that does not accept the case's maltreatment type still receives a (lower) score and the placement is still allowed; the score does not gate creation.

Creating a placement drives a chain of effects. The placement begins `ACTIVE`; the home's `active_placement_count` is incremented and the home's `version` is bumped (this is the increment that a concurrent stale client would miss). The child transitions from `IN_HOME` to `PLACED`, the child's `current_placement_id` is set to the new placement's `id`, and the child's `version` is bumped. And if this is the **first** placement for the child on this case — the moment of removal into care — the case transitions from `OPEN` to `IN_PLACEMENT`, the case's `removal_date` is set to the current clock (anchoring the federal permanency clock; it is set only if still null), and the case's `version` is bumped. A child that was previously `REMOVED` by a disruption can be re-placed by the same operation; in that re-placement the case is already `IN_PLACEMENT` and its `removal_date` is left unchanged, while the child moves from `REMOVED` back to `PLACED`.

### 3.6. The Permanency Clock and ASFA Filing Pressure

The federal Adoption and Safe Families Act imposes a clock on every removed child, and the system tracks it on the `Case`. The case's `months_in_care` is the number of **completed whole months** that have elapsed from `removal_date` to the current clock — counted by month anniversaries, not by dividing days. A removal on the third of a month counts a given month only once the third of the following month is reached; partial months do not count. When `removal_date` is null (no child yet removed), `months_in_care` is 0 and `tpr_clock_breached` is false.

The case's `tpr_clock_breached` flag captures the ASFA "15 of the most recent 22 months" filing trigger. For a single continuous removal episode, the child has been in care for `months_in_care` consecutive months, so the trigger reduces to a simple threshold: `tpr_clock_breached` is true once `months_in_care` is at least 15, and false otherwise. (The statute's 22-month window is the outer bound of the look-back; with one continuous episode the operative number is the 15-month count.) Below 15 months there is no filing pressure; at 15 months or more, the agency is expected to move toward terminating parental rights or to document a compelling exception.

These two computed fields are refreshed whenever a case is read, and may also be explicitly recomputed and persisted against the current clock by an on-demand recompute operation owned by the caseworker.

### 3.7. Disruptions, Suspensions, and the Re-Placement Cycle

Placements end, and how they end determines what happens to the child and the bed. A caseworker may **disrupt** an `ACTIVE` placement directly: the placement moves from `ACTIVE` to `DISRUPTED`, its `end_at` is set to the current clock, the child moves to `REMOVED` with `current_placement_id` cleared, the home's `active_placement_count` is decremented by one, and the `version` of placement, child, and home are each bumped. A `REMOVED` child is not adrift — the caseworker re-places them into a new home by the ordinary placement-create operation, which returns the child to `PLACED`; because the case is already `IN_PLACEMENT`, this re-placement does not move `removal_date`.

The same disruption cascade can be triggered indirectly by the foster home itself. When a `LICENSED` home is **suspended**, every one of its `ACTIVE` placements is transitioned to `DISRUPTED`, each affected child is set to `REMOVED` with their `current_placement_id` cleared, the home's `active_placement_count` is zeroed, and the home's `version` is bumped. When a home's license **lapses** — a system sweep finds the current clock has passed the home's `license_expires_at` while the home is `LICENSED` or `PROVISIONAL` — the home moves to the terminal `EXPIRED` state and the identical placement-disruption cascade fires (every active placement disrupted, every child removed, the count zeroed, the `version` bumped). Suspension and expiry thus protect children by the same mechanism: a home that can no longer safely hold a bed releases all of them at once.

A placement may also end **into permanency** rather than into disruption. A caseworker ends an `ACTIVE` placement to reunification when the child's case has `permanency_goal` `REUNIFICATION` and the case's `CasePlan` is `COMPLETED`; the placement moves to `ENDED_REUNIFIED`, its `end_at` is set to the current clock, the home's `active_placement_count` is decremented, and the `version` is bumped. A placement ends to adoption when the case has `permanency_goal` `ADOPTION` and a `TPR` hearing on the case has been `HELD` with ruling `TERMINATE_RIGHTS`; the placement moves to `ENDED_ADOPTED` with the same end-time, count-decrement, and version effects. An end-to-reunification attempted on a case whose goal is not `REUNIFICATION` (or whose plan is not `COMPLETED`) is rejected — a goal that does not match the requested action surfaces `ERR_GOAL_MISMATCH`, and a plan that is required to be complete but is not surfaces `ERR_PLAN_NOT_COMPLETE`. An end-to-adoption without the `TERMINATE_RIGHTS` ruling on a `HELD` `TPR` hearing is rejected with `ERR_TPR_NOT_TERMINATED`.

### 3.8. The Case Plan, Visitation, and Compliance

Every reunification effort is governed by a court-supervised `CasePlan`. A caseworker creates a plan for a case, supplying the `case_id` it governs, the `required_visits_per_month` it mandates (an integer from 0 to 12), and the `objectives_total` (the count of reunification objectives, which must be at least 1; a value below 1 is rejected with `ERR_VALIDATION_LIMIT`). A new plan is born `DRAFT` with `objectives_met` at 0 and `compliance_pct` at 0.

A plan's progress is tracked by **compliance**. The caseworker updates `objectives_met` to an absolute completed count; the supplied value is clamped to lie between 0 and `objectives_total` inclusive, and the plan's `compliance_pct` is recomputed as the quotient of `objectives_met` over `objectives_total`, multiplied by 100, rounded half-up to two decimal places. A plan with all objectives met reads exactly 100.00; any plan short of its total reads below 100.00.

The plan moves through its own lifecycle. A `DRAFT` plan is activated to `ACTIVE` only once a `DISPOSITION` hearing on the case has been `HELD`; activating a draft without that held disposition hearing is rejected with `ERR_HEARING_PREREQ_MISSING`. An `ACTIVE` plan may be sent back for `REVISION` and a plan in `REVISION` is re-activated to `ACTIVE` (this revision cycle does not require the disposition prerequisite a second time). An `ACTIVE` plan may be **completed** only when its `compliance_pct` is at least 100 — every objective met — and a completion attempt on a plan below that mark is rejected with `ERR_PLAN_NOT_COMPLETE`. Each of these transitions bumps the plan's `version`.

Under an active plan, the caseworker schedules `Visitation` events — supervised or unsupervised contact between parent and child. A visit names the `case_plan_id` that mandates it, the `child_id` attending, the required `supervision` level (`SUPERVISED` or `UNSUPERVISED`), and the visit window bounded by `window_start` and `window_end`. The window must be well-formed: `window_end` must be strictly after `window_start`, else the schedule is rejected with `ERR_INVALID_WINDOW`. Visits also may not collide: a new `SCHEDULED` visit for the same child whose window, treated as a half-open interval from `window_start` up to but not including `window_end`, overlaps an existing `SCHEDULED` visit for that same child is rejected with `ERR_VISIT_OVERLAP`. Because the interval is half-open, two visits that merely touch — one ending exactly when the next begins — do not overlap and are both allowed.

A scheduled visit reaches one of three terminal outcomes. It is marked **occurred** only once the current clock has reached or passed its `window_start` (moving `SCHEDULED` to `OCCURRED`). It is marked **missed** only once the current clock has reached or passed its `window_end` (moving `SCHEDULED` to `MISSED`). And it is **cancelled** only while the current clock is still strictly before its `window_start` (moving `SCHEDULED` to `CANCELLED`). Each of these bumps the visitation's `version`; an attempt that violates the timing precondition or operates on a non-scheduled visit fails the state guard.

When a reunification case has demonstrated enough progress, the caseworker may begin a **trial home visit** — the child lives at home but remains legally in care. This is permitted only when the child is `PLACED`, the case's `permanency_goal` is `REUNIFICATION`, and the case's `CasePlan` has `compliance_pct` of at least 80. On success the child moves from `PLACED` to `TRIAL_HOME_VISIT` and the child's `version` is bumped. A failing trial is revoked, returning the child from `TRIAL_HOME_VISIT` to `PLACED` and bumping the `version`.

### 3.9. The Hearing Docket and Permanency Outcomes

Dependency cases live under court supervision, and the `Hearing` docket is where judicial authority enters the system. A hearing is scheduled (by a caseworker or a judge) on a case by naming the `case_id`, the statutory `hearing_type` (one of `SHELTER`, `ADJUDICATION`, `DISPOSITION`, `REVIEW`, `PERMANENCY`, or `TPR`), and the `scheduled_at` instant. A new hearing is born `SCHEDULED` with `ruling` null. The docket enforces spacing: a new `SCHEDULED` hearing whose `scheduled_at` falls within 30 minutes — inclusive on both sides — of an existing `SCHEDULED` hearing on the same case is rejected with `ERR_HEARING_OVERLAP`. A new hearing exactly 30 minutes from an existing one collides; one strictly more than 30 minutes away does not.

A `Judge` presides. Holding a scheduled hearing requires that the current clock has reached or passed its `scheduled_at` and that a `ruling` is provided in the request; on success the hearing moves from `SCHEDULED` to `HELD` and the `version` is bumped. The recorded `ruling` is one of `CONTINUE_PLACEMENT`, `RETURN_HOME`, `CHANGE_GOAL_ADOPTION`, or `TERMINATE_RIGHTS`. A ruling of `CHANGE_GOAL_ADOPTION` has a cross-entity effect: it sets the case's `permanency_goal` to `ADOPTION`. A ruling of `RETURN_HOME` on a case already in `PERMANENCY_PLANNING` leaves the goal at `REUNIFICATION`. A judge may also **continue** a scheduled hearing (moving `SCHEDULED` to `CONTINUED`), later **reschedule** a continued hearing back to `SCHEDULED` at a newly supplied `scheduled_at`, or **vacate** a scheduled hearing outright (moving `SCHEDULED` to `VACATED`). Each of these bumps the hearing's `version`.

Held hearings gate the case's permanency progression. A case advances from `IN_PLACEMENT` to `PERMANENCY_PLANNING` only when a `PERMANENCY` hearing on the case has been `HELD`; without that held permanency hearing the advance is rejected with `ERR_HEARING_PREREQ_MISSING`. From `PERMANENCY_PLANNING`, the case is **closed** to exactly one of three permanency outcomes, selected by the case's `permanency_goal` and its gates, all evaluated in equal measure:

- **Reunification close** (`CLOSED_REUNIFIED`): permitted when `permanency_goal` is `REUNIFICATION`, the case's `CasePlan` is `COMPLETED`, and the child's active placement (if any) has ended as `ENDED_REUNIFIED`. A goal other than `REUNIFICATION` yields `ERR_GOAL_MISMATCH`; an incomplete plan yields `ERR_PLAN_NOT_COMPLETE`.
- **Adoption close** (`CLOSED_ADOPTED`): permitted when `permanency_goal` is `ADOPTION` and a `TPR` hearing on the case has been `HELD` with ruling `TERMINATE_RIGHTS`. A goal other than `ADOPTION` yields `ERR_GOAL_MISMATCH`; the missing termination yields `ERR_TPR_NOT_TERMINATED`.
- **APPLA close** (`CLOSED_APPLA`, Another Planned Permanent Living Arrangement): permitted when `permanency_goal` is `APPLA` and the child's `age_years` is at least 16. A goal other than `APPLA` yields `ERR_GOAL_MISMATCH`; a child under 16 yields `ERR_AGE_NOT_ELIGIBLE`.

Whichever branch fires, closing the case is a cascade: the case moves to its terminal `CLOSED_*` state and its `version` is bumped, and the child is driven to `PERMANENT` (the system event that carries a child from `PLACED` or `TRIAL_HOME_VISIT` to the terminal `PERMANENT` state, bumping the child's `version`).

### 3.10. Aging Out

A youth who reaches the age of majority while still in care emancipates rather than achieving family permanency. The caseworker ages out a child who is `PLACED` or in `TRIAL_HOME_VISIT` and whose `age_years` is at least 18; an attempt on a younger child is rejected with `ERR_AGE_NOT_ELIGIBLE`. On success the child moves to the terminal `AGED_OUT` state. If the child still holds an `ACTIVE` placement at that moment, that placement is disrupted (moved to `DISRUPTED`) and the home's `active_placement_count` is decremented — emancipation releases the bed. The child's `version` is bumped.

## 4. Endpoint Definitions

All endpoints accept and return the standard envelope of Section 2.2. Creating a new resource returns HTTP 201; all other successful operations — reads, list, state transitions, and computations — return HTTP 200. Request bodies, the fields each operation consumes, and the side effects each triggers are described in Section 3; the table below lists only method, path, purpose, and the roles permitted to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set` | Set the logical system UTC clock to a fixed instant (test-driving). | Admin |
| POST | `/caseworkers` | Register a caseworker. | Admin |
| GET | `/caseworkers/{id}` | Fetch a caseworker. | Admin, IntakeScreener, Investigator, Caseworker, LicensingWorker, Judge |
| GET | `/caseworkers` | List caseworkers (filter by `role_type`). | Admin |
| POST | `/referrals` | Record a hotline referral. | IntakeScreener |
| GET | `/referrals/{id}` | Fetch a referral. | Admin, IntakeScreener, Investigator, Caseworker |
| GET | `/referrals` | List referrals (filter by `status`, `screened_in_by`, `linked_case_id`). | Admin, IntakeScreener, Caseworker |
| POST | `/referrals/{id}/screen` | Screen a referral IN or OUT; compute score and priority. | IntakeScreener |
| POST | `/investigations` | Open an investigation on a screened-in referral. | Caseworker |
| GET | `/investigations/{id}` | Fetch an investigation. | Admin, Caseworker, Investigator |
| GET | `/investigations` | List investigations (filter by `referral_id`, `investigator_id`, `status`). | Admin, Caseworker, Investigator |
| POST | `/investigations/{id}/start` | Investigator begins the home visit. | Investigator |
| POST | `/investigations/{id}/decision` | Record safety factors and capacity; compute decision. | Investigator |
| POST | `/cases` | Open a dependency case; link the originating referral. | Caseworker |
| GET | `/cases/{id}` | Fetch a case (recomputes the permanency clock). | Admin, Caseworker, Judge |
| GET | `/cases` | List cases (filter by `status`, `permanency_goal`, `investigation_id`). | Admin, Caseworker, Judge |
| POST | `/cases/{id}/recompute-clock` | Recompute and persist months-in-care and the breach flag. | Caseworker |
| POST | `/cases/{id}/advance-permanency` | Advance an in-placement case into permanency planning. | Caseworker |
| POST | `/cases/{id}/close` | Close the case to its permanency outcome. | Caseworker |
| POST | `/children` | Register a child on an open case. | Caseworker |
| GET | `/children/{id}` | Fetch a child (recomputes age). | Admin, Caseworker, Judge |
| GET | `/children` | List children (filter by `case_id`, `status`, `current_placement_id`). | Admin, Caseworker, Judge |
| POST | `/children/{id}/trial-home-visit` | Begin a reunification trial home visit. | Caseworker |
| POST | `/children/{id}/revoke-trial` | Revoke a failing trial; return child to placement. | Caseworker |
| POST | `/children/{id}/age-out` | Emancipate a child who has reached aging-out age. | Caseworker |
| POST | `/foster-homes` | Register a foster home (PENDING license). | LicensingWorker |
| GET | `/foster-homes/{id}` | Fetch a foster home (recomputes count and clearances). | Admin, LicensingWorker, Caseworker |
| GET | `/foster-homes` | List foster homes (filter by `license_status`, `licensing_worker_id`). | Admin, LicensingWorker, Caseworker |
| POST | `/foster-homes/{id}/license` | Issue a full license (OCC-guarded). | LicensingWorker |
| POST | `/foster-homes/{id}/license-provisional` | Issue a provisional license. | LicensingWorker |
| POST | `/foster-homes/{id}/suspend` | Suspend a licensed home; disrupt its placements. | LicensingWorker |
| POST | `/foster-homes/{id}/reinstate` | Reinstate a suspended home. | LicensingWorker |
| POST | `/foster-homes/{id}/expire-check` | System sweep: expire a home past its license expiry. | Admin |
| POST | `/caregiver-screenings` | Add a household-member background check. | LicensingWorker |
| GET | `/caregiver-screenings/{id}` | Fetch a caregiver screening. | Admin, LicensingWorker |
| GET | `/caregiver-screenings` | List caregiver screenings (filter by `foster_home_id`, `status`). | Admin, LicensingWorker |
| POST | `/caregiver-screenings/{id}/resolve` | Resolve a pending screening to CLEARED or FLAGGED. | LicensingWorker |
| POST | `/placements` | Place a child into a licensed home's bed (OCC-guarded). | Caseworker |
| GET | `/placements/{id}` | Fetch a placement. | Admin, Caseworker, LicensingWorker |
| GET | `/placements` | List placements (filter by `child_id`, `foster_home_id`, `case_id`, `status`). | Admin, Caseworker, LicensingWorker |
| POST | `/placements/{id}/disrupt` | Disrupt an active placement; release the bed. | Caseworker |
| POST | `/placements/{id}/end-reunified` | End an active placement to reunification. | Caseworker |
| POST | `/placements/{id}/end-adopted` | End an active placement to adoption. | Caseworker |
| POST | `/case-plans` | Create a case plan (DRAFT) for a case. | Caseworker |
| GET | `/case-plans/{id}` | Fetch a case plan (includes compliance). | Admin, Caseworker, Judge |
| GET | `/case-plans` | List case plans (filter by `case_id`, `status`). | Admin, Caseworker, Judge |
| POST | `/case-plans/{id}/objectives` | Update objectives met; recompute compliance. | Caseworker |
| POST | `/case-plans/{id}/activate` | Activate a DRAFT or REVISION plan. | Caseworker |
| POST | `/case-plans/{id}/revise` | Send an active plan back for revision. | Caseworker |
| POST | `/case-plans/{id}/complete` | Complete an active plan (full compliance required). | Caseworker |
| POST | `/visitations` | Schedule a parent-child visit. | Caseworker |
| GET | `/visitations/{id}` | Fetch a visitation. | Admin, Caseworker |
| GET | `/visitations` | List visitations (filter by `case_plan_id`, `child_id`, `status`). | Admin, Caseworker |
| POST | `/visitations/{id}/mark-occurred` | Mark a scheduled visit as occurred. | Caseworker |
| POST | `/visitations/{id}/mark-missed` | Mark a scheduled visit as missed. | Caseworker |
| POST | `/visitations/{id}/cancel` | Cancel a scheduled visit before its window opens. | Caseworker |
| POST | `/hearings` | Schedule a dependency hearing on a case. | Caseworker, Judge |
| GET | `/hearings/{id}` | Fetch a hearing. | Admin, Caseworker, Judge |
| GET | `/hearings` | List hearings (filter by `case_id`, `hearing_type`, `status`). | Admin, Caseworker, Judge |
| POST | `/hearings/{id}/hold` | Hold a scheduled hearing and record a ruling. | Judge |
| POST | `/hearings/{id}/continue` | Continue (pause) a scheduled hearing. | Judge |
| POST | `/hearings/{id}/reschedule` | Reschedule a continued hearing to a new time. | Judge |
| POST | `/hearings/{id}/vacate` | Vacate a scheduled hearing. | Judge |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SOD_CONFLICT` | 409 |
| `ERR_REFERRAL_NOT_SCREENED_IN` | 409 |
| `ERR_INVESTIGATION_NOT_REMOVAL` | 409 |
| `ERR_HOME_NOT_LICENSED` | 409 |
| `ERR_CLEARANCE_FLAGGED` | 409 |
| `ERR_CLEARANCES_INCOMPLETE` | 409 |
| `ERR_AGE_NOT_LICENSED` | 409 |
| `ERR_NO_BEDS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_VISIT_OVERLAP` | 409 |
| `ERR_HEARING_OVERLAP` | 409 |
| `ERR_PLAN_NOT_COMPLETE` | 409 |
| `ERR_GOAL_MISMATCH` | 409 |
| `ERR_HEARING_PREREQ_MISSING` | 409 |
| `ERR_AGE_NOT_ELIGIBLE` | 409 |
| `ERR_TPR_NOT_TERMINATED` | 409 |
| `ERR_VALIDATION_LIMIT` | 422 |
