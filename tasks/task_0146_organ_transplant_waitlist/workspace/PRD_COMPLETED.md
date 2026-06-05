# Organ Transplant Waitlist API — Product Requirements Document

## 1. Introduction

Organ allocation in the United States is governed by a national waitlist in which medical urgency, time already waited, biological compatibility, and geography all compete to decide who receives a scarce, time-critical organ. This document specifies an API that operationalizes that waitlist end-to-end: transplant centers register and manage their candidates, clinicians submit laboratory panels that are scored into a single comparable urgency number, organ procurement organizations register recovered organs and run allocation policy against the candidate pool, and offers are negotiated against a hard cold-ischemia clock until an organ is either accepted into a transplant or discarded.

The system serves three classes of actor whose interests deliberately differ. A listing center advocates for its own candidates; a procurement organization stewards a recovered organ that is decaying by the hour and must place it before it is no longer viable; and the national regulator audits the whole flow and accepts the regulatory reports that close each case. The benchmark value of this domain lies in its dual scoring variants (adult versus pediatric urgency are computed by entirely different formulas), its cascading state machines (a single acceptance simultaneously allocates an organ, transplants a candidate, withdraws a registration, rescinds sibling offers, and invalidates a match run), and its optimistic-concurrency discipline around an organ whose version advances every time it is touched.

Every timestamp the system reasons about — waiting-time accrual, offer response deadlines, organ viability windows, offer expiry — is read from a single deterministic clock so that the behavior is fully reproducible. The remainder of this document defines the global contract (Section 2), the business logic and workflows (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity under which the principal acts. A request missing either header, or carrying a value that is not a recognized role, is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles, spelled precisely as follows: `UNOSAdmin`, `TransplantCenter`, and `OrganProcurementOrg`.

When `X-User-Role` is `TransplantCenter`, `X-User-ID` is the `id` of the acting transplant center; ownership checks on any resource that references a transplant center compare the resource's owning-center foreign key to `X-User-ID`. Concretely, a candidate's `center_id` must equal `X-User-ID` for the acting center to mutate that candidate, and the same ownership chain extends transitively to the candidate's clinical scores and registrations, to offers and transplants that reference the candidate, and to follow-ups under those transplants. A center attempting to mutate a candidate, offer, transplant, or follow-up that it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

When `X-User-Role` is `OrganProcurementOrg`, `X-User-ID` is the `id` of the acting procurement organization; ownership checks on any resource that references a procurement organization compare the resource's `opo_id` to `X-User-ID`. A donor organ's `opo_id` ties the organ, and the allocation runs and offers derived from it, to the acting organization.

When `X-User-Role` is `UNOSAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The regulator manages reference data, accepts or rejects reports, and drives the deterministic clock; the server does not compare this identifier to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. Out-of-range or non-integer pagination values are not rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is lowered to 100, a negative `offset` is raised to 0, and a value that does not parse as an integer falls back to its default (10 for `limit`, 0 for `offset`).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with insertion order as the deterministic tiebreaker when two resources share a creation timestamp.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system are full first-class entities and carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created. This and `updated_at` are record-management timestamps stamped from real server wall-clock time, independent of the deterministic business clock of Section 2.5 (which governs only the "now" used in business-temporal reasoning).
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every modification to the resource.
- `version` — a system-managed integer that begins at its initial value of 1 and increments by one with every mutation of the resource. It underpins optimistic concurrency control (Section 2.7). The donor organ, match run, and offer are the exception: a match run and an offer carry, in their own `version` field, the donor organ's `version` as it stood immediately after the run completed or the offer was issued (the OCC token of Section 2.7), rather than an independent per-resource mutation count — so the value a caller next chains into an organ-touching operation comes from re-reading the organ itself.

Two kinds of resource are deliberately leaner. A **match-list entry** — the append-only ranking row produced by an allocation run — carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because once written it is never modified. The **system clock** is a server-owned singleton that exposes only its `current_utc` value and is never versioned. All other resources (centers, procurement organizations, candidates, clinical scores, registrations, donor organs, match runs, offers, transplants, follow-ups, and reports) carry the full common-field set above.

Derived fields are first-class mutations. When the system recomputes a candidate's `current_meld_peld`, `waiting_time_days`, or any state field as a side effect of another operation, that recomputation refreshes the affected resource's `updated_at` and increments its `version` exactly as a direct edit would.

### 2.5. Deterministic Clock and Temporal Reasoning

Every notion of "now" in the system — waiting-time accrual, an offer's response deadline, the cold-ischemia viability window, and offer-expiry checks — is read from a single deterministic clock rather than wall-clock time. The clock exposes one value, `current_utc`. An administrator advances it by supplying a target instant, after which all subsequent now-reads use that value. This makes time-dependent behavior fully reproducible: setting the clock forward past a deadline is the mechanism by which tests reach expiry and viability boundaries.

The clock is mutated through a dedicated test-driving capability that accepts a single field, `to_iso8601`, the instant to which `current_utc` is set. Reading the clock returns the current `current_utc`. Before the administrator has set the clock for the first time, `current_utc` reads a fixed default epoch of `1970-01-01T00:00:00.000Z`.

### 2.6. Nested Resource Retrieval and Referential Validation

Several resources are addressed beneath a parent in the URL hierarchy — clinical scores and registrations beneath a candidate, entries beneath a match run, follow-ups beneath a transplant. For any request whose path or body names more than one resource, the system validates referenced resources left-to-right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request for a follow-up under a non-existent transplant therefore fails on the transplant before the follow-up is ever consulted. This same left-to-right existence check governs body references: a foreign key named in a create payload (for example the `candidate_id`, `donor_organ_id`, `match_run_id`, or `offer_id` of a new resource) must resolve before any business rule is evaluated.

Existence (`ERR_NOT_FOUND`) is checked before ownership (`ERR_NOT_RESOURCE_OWNER`), which is checked before field-shape validation, which is checked before any state, concurrency, or business-safety rule. The full priority ordering is given in Section 2.8.

### 2.7. Optimistic Concurrency Control on the Donor Organ

A recovered donor organ is the single contended resource in the system: its `version` advances every time it is matched, offered, accepted, transplanted, or discarded. Two operations therefore require the caller to prove it is acting on a current view of the organ by supplying `expected_donor_organ_version`, the `version` the caller last observed on the organ.

Starting a new allocation run requires `expected_donor_organ_version` to equal the target organ's current `version`. If a prior run or a discard has already advanced the organ's version since the caller last read it, the caller's view is stale and the run is rejected with `ERR_STALE_ORGAN_VERSION` (HTTP 412), rather than producing a ranking against an out-of-date organ state.

Issuing an offer directly to a candidate likewise requires `expected_donor_organ_version` to equal the organ's current `version`. If another writer has advanced the organ's version since the caller last read it — for example by accepting an offer (which moves the organ to `ALLOCATED` and bumps `version`) or by re-running the match — the issuance is rejected with `ERR_STALE_ORGAN_VERSION` (HTTP 412), preventing an offer from being created on an organ that is no longer in a matchable state for that view.

Starting a run, issuing a targeted offer, issuing an offer through offer-next, and accepting an offer each carry `expected_donor_organ_version` and re-check it against the organ's current `version`, rejecting a mismatch with `ERR_STALE_ORGAN_VERSION` (HTTP 412); offer-next likewise supplies this field and the value it should carry is derived from the organ it acts on. No other endpoint takes a version field.

### 2.8. Validation Priority Ordering

When several conditions could each reject a single request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. The order is:

1. Authentication — both headers present and valid, else `ERR_UNAUTHENTICATED`.
2. Authorization — the role may perform this operation, else `ERR_UNAUTHORIZED`.
3. Existence — every path- and body-referenced resource exists, validated left-to-right, else `ERR_NOT_FOUND`.
4. Resource ownership — the acting transplant center owns the candidate, offer, transplant, or follow-up being mutated (its `X-User-ID` equals the resource's owning `center_id`, directly or through the referenced candidate), else `ERR_NOT_RESOURCE_OWNER`.
5. Request shape — required body fields are present and well-typed, enums are in range, arrays have the correct length, and numbers are positive, else `ERR_INVALID_REQUEST`.
6. Uniqueness — `(center_id, mrn)` for a candidate, `unos_center_code` for a center, and `opo_code` for a procurement organization are each unique, else `ERR_DUPLICATE_RESOURCE`.
7. State — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`.
8. Optimistic concurrency — `expected_donor_organ_version` equals the organ's `version` on run-start and offer-issuance, else `ERR_STALE_ORGAN_VERSION`.

After these eight tiers, the remaining business-safety and business-temporal checks specific to each operation apply, as described in Section 3. Where one operation carries several such later checks, the per-operation ordering is stated in the workflow that owns it (for example, offer issuance and offer acceptance each enumerate their compatibility and window checks in order).

### 2.9. Allocation Scoring Precision

Clinical urgency scores and allocation priority points are produced by the formulas in Section 3 and obey strict precision rules. A candidate's finalized clinical score (`allocation_score`) is always an integer constrained to the inclusive range from 6 to 40: the intermediate value is rounded half-up and then clamped so that any result below 6 becomes 6 and any result above 40 becomes 40. The intermediate (`raw_score`) retained for audit is the value produced immediately before that final half-up round and 6-to-40 clamp — that is, the index after the "multiply by 10 and round half-up to the nearest integer" step of Section 3.3 (with the adult sodium adjustment, when it applies, layered onto that rounded integer at full precision); it is stored as a JSON number and is not the fully unrounded linear combination. Allocation priority points are computed by rounding each component half-up to a whole number first and only then summing the components, so the stored `priority_points` is an exact sum of integer parts (except under the broader-sharing geographic adjustment, which applies one further half-up rounding as described in Section 3.5). The actual cold-ischemia duration recorded on a transplant (`cold_ischemia_hours_actual`) is rounded half-up to two decimal places. Wherever this document specifies rounding, "round half up" is the method: a value exactly halfway between two candidates rounds away from zero to the larger magnitude.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Centers and Procurement Organizations

Before any clinical activity can occur, the regulator establishes the participating institutions. A `UNOSAdmin` registers a **transplant center** by supplying its `name`, a `unos_center_code`, the OPTN `region_code`, and its geographic `latitude` and `longitude`. The `unos_center_code` must be unique across all centers; a collision is rejected with `ERR_DUPLICATE_RESOURCE`. The `region_code` is an OPTN region and must be an integer from 1 through 11 inclusive; a value outside that range is rejected as a malformed request.

Symmetrically, a `UNOSAdmin` registers an **organ procurement organization** by supplying its `name`, a unique `opo_code`, its OPTN `region_code` (again an integer from 1 through 11 inclusive), and the `latitude` and `longitude` of its recovery site. A duplicate `opo_code` is rejected with `ERR_DUPLICATE_RESOURCE`. Both kinds of reference record are readable by any authenticated role; only the regulator may create them.

The geographic and regional attributes are not decorative: a candidate's listing center region and a donor organ's procuring-organization region together decide, under the standard allocation policy, whether that candidate is eligible for that organ at all (Section 3.5).

### 3.2. Candidate Registration and the Two Status Dimensions

A `TransplantCenter` registers a **candidate** it intends to list. Registration requires the owning `center_id`, the center's medical record number `mrn`, the `organ_type` sought (one of `LIVER`, `KIDNEY`, `HEART`, or `LUNG`), the ABO `blood_type` (one of `O`, `A`, `B`, or `AB`), the patient's `date_of_birth`, `height_cm`, and `weight_kg`, and three two-element antigen arrays `hla_a`, `hla_b`, and `hla_dr`. Each HLA array must contain exactly two allele strings; `height_cm` and `weight_kg` must each be greater than zero. The center may also supply `unacceptable_antigens`, the list of antigens to which the patient is sensitized; when omitted it defaults to an empty list. The pair `(center_id, mrn)` must be unique — a second candidate with the same medical record number at the same center is rejected with `ERR_DUPLICATE_RESOURCE`.

A candidate carries **two independent status dimensions** that evolve separately. The first, `listing_status`, follows the UNOS listing lifecycle through the values `DRAFT`, `LISTED`, `TRANSPLANTED`, and `REMOVED`; a new candidate begins in `DRAFT`. The second, `medical_status`, expresses clinical readiness and toggles between `ACTIVE` and `INACTIVE`; a new candidate begins `ACTIVE`. These dimensions are orthogonal: a listed candidate that is deactivated remains `LISTED` but stops competing for organs while `INACTIVE`.

Several candidate fields are computed rather than supplied. The flag `is_pediatric` is null while the candidate is in `DRAFT` and is determined and persisted at listing time: the patient's age in whole years is the number of complete 365.25-day periods between `date_of_birth` and the moment of listing — that is, the elapsed time from birth to listing divided by 365.25 days and taken as a floor to a whole number — and the candidate is pediatric when that age is strictly less than 12. The pediatric flag selects which scoring formula applies. The field `current_meld_peld` holds the candidate's latest finalized allocation score and is 0 until the first clinical score is finalized. The timestamp `listed_at` is null while the candidate is in `DRAFT` and is set when the candidate first becomes `LISTED`; it anchors waiting-time accrual. The integer `waiting_time_days` is the whole number of days the candidate has been continuously listed and active (Section 3.4). The field `removal_reason` is null until the candidate leaves the waitlist, at which point it records why.

Reading a single candidate recomputes `waiting_time_days` against the current clock before returning, so the value is always current as of the latest clock reading. Candidates may be listed and filtered by `center_id`, `organ_type`, and `listing_status`.

### 3.3. Clinical Scoring: The Two Urgency Formulas

A candidate cannot be listed without a comparable urgency number, and that number comes from a **clinical score**. A `TransplantCenter` attaches a score to one of its candidates by supplying that candidate's identifier together with a laboratory panel: `bilirubin_mg_dl`, `inr`, `creatinine_mg_dl`, `sodium_mmol_l`, `albumin_g_dl`, the optional booleans `growth_failure` (defaulting to false) and `on_dialysis_twice_in_week` (defaulting to false), and the lab draw timestamp `effective_at`. Each of the four laboratory concentrations must be greater than zero. A new score is created in `DRAFT` status and carries the candidate it scores via `candidate_id`. The score's lifecycle runs through `DRAFT`, `FINALIZED`, and `SUPERSEDED`.

Finalizing a score is where the urgency number is produced. Finalization is permitted only when the score is currently `DRAFT` — otherwise `ERR_INVALID_STATE` — and only when the parent candidate is not in `REMOVED` listing status. On finalization the system computes three derived fields: `score_kind` (either `MELD_NA` or `PELD`), the `raw_score`, and the integer `allocation_score`. Which formula runs depends on the candidate's `is_pediatric` flag. When the candidate has already been listed, that persisted flag is used directly; when finalization occurs before listing (so `is_pediatric` is still null), the formula branch is chosen by computing the pediatric test (age in whole years strictly less than 12, by the 365.25-day rule of Section 3.2) against the score's `effective_at` instant, without persisting the flag.

**For an adult candidate** (not pediatric), the MELD-Na formula applies and `score_kind` is `MELD_NA`. First the inputs are floored to clinical lower bounds: bilirubin is taken as the greater of the measured `bilirubin_mg_dl` and 1.0, and INR as the greater of the measured `inr` and 1.0. Creatinine is handled specially: when `on_dialysis_twice_in_week` is true, creatinine is forced to 4.0 regardless of the measured value; otherwise creatinine is the measured `creatinine_mg_dl` first floored at 1.0 and then capped at 4.0 (that is, clamped into the inclusive 1.0-to-4.0 band). A base index is then formed as 0.957 times the natural logarithm of the clamped creatinine, plus 0.378 times the natural logarithm of the clamped bilirubin, plus 1.120 times the natural logarithm of the clamped INR, plus 0.643; this base index is multiplied by 10 and rounded half-up to the nearest integer. A sodium adjustment is applied only when that rounded base index exceeds 11: sodium is clamped into the inclusive band from 125.0 to 137.0, and the adjusted value is the base index plus 1.32 times (137 minus the clamped sodium), minus the product of 0.033, the base index, and (137 minus the clamped sodium). When the rounded base index is 11 or below, no sodium adjustment is made and the adjusted value equals the base index. Finally the adjusted value is rounded half-up and clamped into the inclusive 6-to-40 band to yield `allocation_score`.

**For a pediatric candidate**, the PELD formula applies and `score_kind` is `PELD`. PELD uses a different input set entirely — it relies on albumin and the growth-failure flag and does not use creatinine or sodium. Bilirubin and INR are floored to 1.0 exactly as above. Albumin is taken as the measured `albumin_g_dl` and is **not** floored. A growth-failure contribution of 0.667 is added when `growth_failure` is true and is 0 otherwise. The linear sum is 0.480 times the natural logarithm of the clamped bilirubin, plus 1.857 times the natural logarithm of the clamped INR, minus 0.687 times the natural logarithm of the albumin, plus the growth-failure contribution, plus 0.436. That sum is multiplied by 10 and rounded half-up to the nearest integer, and the result is then rounded half-up and clamped into the inclusive 6-to-40 band to yield `allocation_score`.

Finalization has two cascading effects. If the candidate already has a prior `FINALIZED` clinical score, that prior score is moved to `SUPERSEDED` (superseded scores are retained for audit and are never deleted). The system then recomputes `current_meld_peld` on the candidate to the `allocation_score` of the now-most-recent finalized score, where "most recent" is judged by `effective_at`, with ties broken by `created_at`. A candidate's clinical scores can be listed beneath the candidate and filtered by `status`, and an individual score may be fetched directly.

### 3.4. Listing, Readiness, and Waiting-Time Accrual

Listing a candidate moves `listing_status` from `DRAFT` to `LISTED`. The transition is permitted only when the candidate has at least one `FINALIZED` clinical score — equivalently, when `current_meld_peld` is greater than 0 — otherwise the request is rejected with `ERR_NO_FINALIZED_SCORE`; and only when the candidate's `medical_status` is `ACTIVE`. Listing sets `listed_at` to the current clock instant, creates an `ACTIVE` **waitlist registration** for the candidate (copying the candidate's `organ_type` into the registration so it competes in the correct organ pool), and begins waiting-time accrual from `listed_at`. A registration carries the `candidate_id` it belongs to, its copied `organ_type`, a `status` among `ACTIVE`, `SUSPENDED`, and `WITHDRAWN`, a `suspended_at` timestamp that is null while active, and a `withdrawn_reason` that is null until withdrawal.

**Waiting time** accrues only while a candidate is simultaneously `LISTED` and `ACTIVE`. The system tracks accrual as a series of intervals. An interval is open while both conditions hold; it closes when the candidate is deactivated, removed, or transplanted, and a fresh interval opens when the candidate is reactivated. The value `waiting_time_days` is computed by summing, across all intervals, the elapsed seconds of each interval — using the current clock instant as the end of the still-open interval — and then taking the whole number of days, that is, the total seconds divided by 86,400 and floored to an integer. Spans during which the candidate is `INACTIVE` or not `LISTED` contribute nothing.

**Deactivation** moves `medical_status` from `ACTIVE` to `INACTIVE` and is permitted only while the candidate's `listing_status` is `DRAFT` or `LISTED`. If the candidate is `LISTED`, deactivation closes the current accrual interval at the present clock instant (so no further waiting time accrues while inactive) and cascades the candidate's `ACTIVE` registration to `SUSPENDED`, stamping `suspended_at` with the current instant. A deactivated but still-listed candidate keeps its `LISTED` status yet is excluded from allocation runs.

**Reactivation** moves `medical_status` from `INACTIVE` back to `ACTIVE` and is likewise permitted only while `listing_status` is `DRAFT` or `LISTED`. If the candidate is `LISTED`, reactivation opens a new accrual interval starting at the present clock instant and cascades the candidate's `SUSPENDED` registration back to `ACTIVE`, clearing `suspended_at`. A candidate may toggle readiness any number of times; the deactivate and reactivate edges form a cycle.

**Removal** moves `listing_status` from `LISTED` to `REMOVED` and requires a `removal_reason` in the body drawn from `DECEASED`, `IMPROVED`, `TRANSFERRED`, or `OTHER`. (The fifth reason value, `TRANSPLANTED`, is reserved for the system-driven removal that accompanies a transplant and is never supplied by a center on this operation.) Removal is permitted only while the candidate is `LISTED`. It records the supplied `removal_reason`, cascades the candidate's `ACTIVE` registration to `WITHDRAWN` with its `withdrawn_reason` set to the same removal reason, rescinds every still-open offer the candidate holds (each rescinded offer decrements its organ's `open_offer_count` by one, as detailed in Section 3.7), and stops waiting-time accrual.

### 3.5. Donor Organs, Allocation Runs, and the Ranked Match List

An `OrganProcurementOrg` registers a recovered **donor organ** by supplying its `opo_id`, the `organ_type` recovered, the donor's `blood_type`, the donor's `donor_height_cm` and `donor_weight_kg` (each greater than zero), the donor's three antigen arrays `hla_a`, `hla_b`, and `hla_dr`, the `recovered_at` instant that starts the cold-ischemia clock, and `max_cold_ischemia_hours`, the viability window in hours measured from `recovered_at` (greater than zero). A new organ begins in `AVAILABLE` status with `open_offer_count` at 0. The organ's lifecycle spans `AVAILABLE`, `MATCHING`, `ALLOCATED`, `TRANSPLANTED`, and `DISCARDED`. The conserved field `open_offer_count` always equals the number of offers for this organ currently in `OFFERED` status — it rises by one whenever an offer is opened and falls by one whenever an offer leaves the `OFFERED` state, whatever the cause.

**Running allocation** moves the organ from `AVAILABLE` to `MATCHING`. A procurement organization starts a run by supplying the `donor_organ_id`, the `expected_donor_organ_version` (which must match the organ's current `version`, per Section 2.7), and a `policy_code` of either `STANDARD` or `BROADER_SHARING`. The run is permitted only when the organ is `AVAILABLE`. It produces a **match run** and a ranked set of **match-list entries**, sets `ranked_count` to the number of eligible candidates, and increments the organ's `version` by one. A match run carries its `status` (`COMPLETED` on creation, later possibly `INVALIDATED`).

The **eligible pool** for a run consists of every candidate that satisfies all of the following: the candidate's `listing_status` is `LISTED`; the candidate's `medical_status` is `ACTIVE`; the candidate's `organ_type` equals the donor organ's `organ_type`; the candidate is ABO-compatible with the donor; the candidate is size-compatible with the donor; no donor antigen appears in the candidate's `unacceptable_antigens`; and, under the `STANDARD` policy, the candidate's listing-center `region_code` equals the donor organ's procuring-organization `region_code`. Under the `BROADER_SHARING` policy the region restriction is lifted and candidates from any region are eligible. Candidates that are inactive, not listed, of the wrong organ type, ABO-incompatible, size-incompatible, or sensitized against the donor are excluded.

**ABO compatibility** follows the standard donor-to-recipient rules. A donor of type `O` is compatible with recipients of type `O`, `A`, `B`, or `AB`; a donor of type `A` is compatible with recipients of type `A` or `AB`; a donor of type `B` is compatible with recipients of type `B` or `AB`; and a donor of type `AB` is compatible only with a recipient of type `AB`. Compatibility is decided purely by this set membership.

**Size compatibility** is a weight-ratio gate. Let the ratio be the donor's `donor_weight_kg` divided by the candidate's `weight_kg`. For thoracic organs — `HEART` or `LUNG` — the candidate is size-compatible when the ratio is at least 0.80 and at most 1.20. For abdominal organs — `LIVER` or `KIDNEY` — the candidate is size-compatible when the ratio is at least 0.70 and at most 1.50. Both bounds are inclusive in each band.

**Ranking** orders the eligible pool by a composite priority. For each eligible candidate the system computes `priority_points` by rounding several components half-up to whole numbers individually and then summing them. The medical component is the candidate's `current_meld_peld` multiplied by 2.5, rounded half-up. The waiting component is the candidate's `waiting_time_days` capped at 365 days, divided by 365, multiplied by 10, then rounded half-up — so waiting contribution saturates at one year. The HLA component derives from the candidate's mismatch count: `hla_mismatch_count` is the number of the donor's six HLA-A, HLA-B, and HLA-DR antigens that are not shared with the candidate (an integer from 0 to 6), and the HLA component is 6 minus that mismatch count, multiplied by 1.5, rounded half-up. A pediatric candidate receives a flat pediatric component of 8 points; a non-pediatric candidate receives 0. The four rounded components are summed to give `priority_points`. Under the `BROADER_SHARING` policy only, a candidate whose listing-center region differs from the donor organ's procuring-organization region has its summed `priority_points` multiplied by 0.9 and then re-rounded half-up; in-region candidates and all candidates under `STANDARD` policy take the un-adjusted sum.

Entries are ranked in descending order of `priority_points`. Ties are broken in a fixed sequence: first the candidate with the higher `current_meld_peld` ranks ahead; if still tied, the candidate with more `waiting_time_days` ranks ahead; and if still tied, the candidate with the earlier `created_at` ranks ahead. Each **match-list entry** is an append-only row carrying its `match_run_id`, the ranked `candidate_id`, the 1-based `rank` (rank 1 is highest priority), the candidate's `priority_points`, and the candidate's `hla_mismatch_count`. A run's entries may be listed beneath the run, an individual entry fetched directly, and entries listed across runs filtered by `candidate_id` or `match_run_id`. Match runs themselves may be listed and filtered by `donor_organ_id` and `status`.

A match run is **invalidated** — moved from `COMPLETED` to `INVALIDATED` — by the system whenever its organ becomes `ALLOCATED` or `DISCARDED`, or whenever one of its ranked candidates is removed. Once invalidated, the run's results are frozen and no new offer may cite it.

### 3.6. Discarding an Organ

A procurement organization may **discard** a donor organ that cannot be placed. Discard is defined from two states. From `AVAILABLE`, discard simply moves the organ to `DISCARDED` and increments its `version`. From `MATCHING`, discard is permitted only when the cold-ischemia window has elapsed — that is, when the current clock instant is strictly after `recovered_at` plus `max_cold_ischemia_hours` — or when the organ has no offer in `OFFERED` or `ACCEPTED` status; in that case discard cascades every still-open offer for the organ to `EXPIRED` (each decrementing `open_offer_count` by one), moves the organ's match run to `INVALIDATED`, moves the organ to `DISCARDED`, and increments its `version`. A discard attempted from any other state is rejected with `ERR_INVALID_STATE`.

### 3.7. Offers: Targeted Issuance, the Re-Offer Loop, and Negotiation

Once an organ has been matched, the procurement organization places it by issuing **offers** down the ranked list. The offer lifecycle spans `OFFERED`, `ACCEPTED`, `DECLINED`, `EXPIRED`, and `RESCINDED`, beginning in `OFFERED`.

There are two ways to open an offer. A **targeted issuance** names the recipient explicitly: the procurement organization supplies the `donor_organ_id`, the `candidate_id`, the `match_run_id` that produced the ranking, and the `expected_donor_organ_version`. An **offer-next** issuance instead walks the run automatically: the procurement organization supplies only the `expected_donor_organ_version`, and the system selects, in ascending rank order from the organ's latest `COMPLETED` run, the first ranked candidate who does not yet hold any offer for this organ in any status — that is, no offer that is `OFFERED`, `ACCEPTED`, `DECLINED`, `EXPIRED`, or `RESCINDED` (so a "terminal offer" here means any prior or open offer, not only a settled one). If there is no `COMPLETED` run for the organ, or no such candidate remains, offer-next is rejected with `ERR_NO_NEXT_CANDIDATE`. The chosen candidate is then subjected to the same compatibility and timing battery below; offer-next does not skip past a candidate who fails that battery, so a failing chosen candidate causes offer-next to return that battery's error rather than advancing to the next rank. Both forms create an `OFFERED` offer carrying the originating `donor_organ_id`, `candidate_id`, and `match_run_id`; both copy the candidate's `rank` from the match list into `rank_at_offer`; both stamp `offered_at` with the current clock instant; both compute `response_deadline_at`; both increment `open_offer_count`; and both increment the organ's `version`.

Both issuance forms enforce the same battery of compatibility and timing gates before an offer is created. The organ type must match: the offered organ's type must equal the candidate's `organ_type`, else `ERR_ORGAN_TYPE_MISMATCH`. The blood groups must be ABO-compatible; an incompatible pair is rejected with `ERR_ABO_INCOMPATIBLE`. The virtual crossmatch must be negative; if any of the donor's antigens appears in the candidate's `unacceptable_antigens`, the issuance is a positive crossmatch and is rejected with `ERR_POSITIVE_CROSSMATCH`. The size ratio must fall inside the organ-type band of Section 3.5; an out-of-band ratio is rejected with `ERR_SIZE_INCOMPATIBLE`. The viability window must still be open: an offer whose computed `response_deadline_at` would not be strictly later than its `offered_at` means the cold-ischemia window has already closed, and the issuance is rejected with `ERR_ISCHEMIA_WINDOW_CLOSED`. Finally, an organ may hold at most one open offer to a given candidate at a time; a second `OFFERED` offer to a candidate who already holds one for the same organ is rejected with `ERR_DUPLICATE_OPEN_OFFER`. For targeted issuance, the supplied `expected_donor_organ_version` must additionally match the organ's `version`, per Section 2.7.

**The response deadline** is the earlier of two competing windows, computed in a pinned order: first the response window, which is `offered_at` plus one hour; then the ischemia ceiling, which is the organ's `recovered_at` plus its `max_cold_ischemia_hours`. The stored `response_deadline_at` is the earlier of those two instants. This is why a deadline can fall before the nominal one-hour response window: a fast-decaying organ caps the window short.

**Declining** an offer moves it from `OFFERED` to `DECLINED`. The acting center supplies a `decline_reason` drawn from `SIZE_MISMATCH`, `MEDICAL_UNSUITABLE`, `CANDIDATE_UNAVAILABLE`, `CENTER_DECLINE`, or `OTHER`; the reason is recorded and the organ's `open_offer_count` is decremented by one. After a decline, the procurement organization typically issues the next-ranked offer through the offer-next loop, forming the cyclic re-offer pattern that walks the list until an acceptance or exhaustion.

**Expiring** an offer moves it from `OFFERED` to `EXPIRED` and is performed by the procurement organization. Expiry is permitted only when the current clock instant is strictly after the offer's `response_deadline_at`; an attempt to expire an offer whose window is still open (now at or before the deadline) is rejected with `ERR_OFFER_WINDOW_OPEN`. A successful expiry decrements the organ's `open_offer_count` by one.

**Rescission** is never client-initiated; the system moves an offer from `OFFERED` to `RESCINDED` as a cascade when its organ is allocated elsewhere, when its candidate is removed, or when its organ is discarded. Each rescission decrements the organ's `open_offer_count` by one. This is the third way an offer leaves the open state, alongside acceptance, decline, and expiry.

### 3.8. Acceptance and the Allocation Cascade

**Accepting** an offer is the pivotal cascade of the whole system. A `TransplantCenter` accepts by supplying `expected_donor_organ_version`. Acceptance is permitted only when a sequence of conditions all hold. The offer must currently be `OFFERED`, else `ERR_INVALID_STATE`. The response window must still be open: the current clock instant must be at or before `response_deadline_at`; an accept after the deadline is rejected with `ERR_OFFER_WINDOW_CLOSED` (note the boundary — acceptance is valid exactly at the deadline, while expiry requires strictly after it). The candidate must be ready: both `medical_status` equal to `ACTIVE` and `listing_status` equal to `LISTED`, else `ERR_CANDIDATE_NOT_ACTIVE`. The organ must be in `MATCHING`. And the supplied `expected_donor_organ_version` must match the organ's current `version`, else `ERR_STALE_ORGAN_VERSION`.

When acceptance succeeds it sets a chain of consequences in motion. The accepted offer moves to `ACCEPTED` and its own contribution to the organ's `open_offer_count` is decremented. The organ cascades from `MATCHING` to `ALLOCATED`; that allocation rescinds every other still-open offer for the organ (each decrementing `open_offer_count`) and then sets `open_offer_count` to 0, and it increments the organ's `version`. The candidate cascades from `LISTED` to `TRANSPLANTED`, which sets the candidate's `removal_reason` to `TRANSPLANTED`, withdraws the candidate's `ACTIVE` registration to `WITHDRAWN` with `withdrawn_reason` of `TRANSPLANTED`, and stops waiting-time accrual. The offer's match run cascades to `INVALIDATED`. Across this cascade the organ's `version` advances, which is precisely why a stale second writer carrying the pre-acceptance version is later rejected (Section 2.7).

### 3.9. Recording the Transplant and Post-Transplant Follow-Up

With an organ allocated, the receiving center **records the transplant**. A `TransplantCenter` supplies the accepted `offer_id` and the `transplanted_at` instant of the operation. The transplant is created only when the referenced offer is in `ACCEPTED` status and no transplant already exists for it; otherwise the request is rejected with `ERR_OFFER_NOT_ACCEPTED`. On creation the system copies `candidate_id` and `donor_organ_id` from the offer, computes `cold_ischemia_hours_actual` as the elapsed time from the organ's `recovered_at` to `transplanted_at` expressed in hours — the difference in seconds divided by 3,600 — rounded half-up to two decimal places, moves the organ from `ALLOCATED` to `TRANSPLANTED` (incrementing its `version`), and sets the transplant's `graft_status` to `FUNCTIONING`. The graft lifecycle spans `FUNCTIONING`, `AT_RISK`, and `FAILED`. Transplants may be listed and filtered by `offer_id`, `candidate_id`, and `donor_organ_id`.

After a transplant, the center schedules **follow-up visits** at protocol milestones. A follow-up is created beneath its transplant with an `interval_label` of `M1`, `M6`, `M12`, or `M24`, a `scheduled_for` instant, and an optional `graft_functioning` finding that defaults to true. A follow-up's `scheduled_for` may not precede the parent transplant's `transplanted_at`; an earlier schedule is rejected with `ERR_FOLLOWUP_BEFORE_TRANSPLANT`. A new follow-up begins `SCHEDULED`; its lifecycle spans `SCHEDULED`, `COMPLETED`, and `MISSED`. A transplant's follow-ups may be listed and filtered by `status`, and a single follow-up fetched directly.

**Completing** a follow-up moves it from `SCHEDULED` to `COMPLETED` and is permitted only while the follow-up is `SCHEDULED` and the parent transplant's `graft_status` is not `FAILED`. The complete operation takes no request body; the `graft_functioning` finding it acts on is the value recorded on the follow-up when it was scheduled. That finding drives the graft: if the finding is false, the system cascades the transplant from `FUNCTIONING` to `AT_RISK`; if the finding is true and the transplant is currently `AT_RISK`, the system cascades it back from `AT_RISK` to `FUNCTIONING`. Successive visits may therefore toggle the graft between `FUNCTIONING` and `AT_RISK` across the follow-up timeline.

**Marking a follow-up missed** moves it from `SCHEDULED` to `MISSED` and is permitted only when the follow-up is `SCHEDULED` and the current clock instant is strictly after its `scheduled_for`; an attempt while the clock is at or before `scheduled_for` is rejected with `ERR_INVALID_STATE`, and the operation changes no graft status. Separately, a center may **mark a graft failed**, moving the transplant from `AT_RISK` to `FAILED`; this is permitted only when the graft is currently `AT_RISK`, and `FAILED` is terminal.

### 3.10. UNOS Reporting

Each completed case is closed out with a **UNOS report**. A `TransplantCenter` submits a report with a `report_kind` of `TRANSPLANT`, `REMOVAL`, or `FOLLOWUP`, optionally a `transplant_id`, and optionally a `candidate_id`. The subject references must be consistent with the kind: a `TRANSPLANT` or `FOLLOWUP` report requires a `transplant_id` naming an existing transplant, while a `REMOVAL` report requires a `candidate_id` whose candidate is in `REMOVED` listing status; a report whose subject is missing or whose removal candidate is not actually removed is rejected with `ERR_REPORT_SUBJECT_INVALID`. A submitted report stamps `submitted_at` with the current instant and begins in `SUBMITTED` status; its lifecycle spans `SUBMITTED`, `ACCEPTED`, and `REJECTED`. Reports may be listed and filtered by `transplant_id`, `candidate_id`, `report_kind`, and `status`.

Only the regulator adjudicates reports. A `UNOSAdmin` **accepts** a report, moving it from `SUBMITTED` to `ACCEPTED`; acceptance is permitted only while the report is `SUBMITTED` and only when its subject still validates — a `TRANSPLANT`-kind report's referenced transplant must exist and a `REMOVAL`-kind report's referenced candidate must be in `REMOVED` status. Alternatively a `UNOSAdmin` **rejects** a report, moving it from `SUBMITTED` to `REJECTED` and recording the supplied `rejection_reason` (free text); rejection is likewise permitted only while the report is `SUBMITTED`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code; operations that modify an existing resource — including state transitions and finalizations — return a `200 OK` status code. Request bodies, response payloads, side effects, and trigger conditions are intentionally not repeated here; reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/transplant-centers` | Register a transplant center | UNOSAdmin |
| GET | `/transplant-centers/{id}` | Fetch a center | UNOSAdmin, TransplantCenter, OrganProcurementOrg |
| POST | `/organ-procurement-orgs` | Register an OPO | UNOSAdmin |
| GET | `/organ-procurement-orgs/{id}` | Fetch an OPO | UNOSAdmin, TransplantCenter, OrganProcurementOrg |
| POST | `/candidates` | Create a candidate in DRAFT/ACTIVE | TransplantCenter |
| GET | `/candidates` | List candidates; filter by center_id/organ_type/listing_status | UNOSAdmin, TransplantCenter, OrganProcurementOrg |
| GET | `/candidates/{id}` | Fetch a candidate (recomputes waiting_time_days at read) | UNOSAdmin, TransplantCenter, OrganProcurementOrg |
| POST | `/candidates/{id}/list` | List a candidate (DRAFT to LISTED) | TransplantCenter |
| POST | `/candidates/{id}/deactivate` | Set medical_status ACTIVE to INACTIVE | TransplantCenter |
| POST | `/candidates/{id}/reactivate` | Set medical_status INACTIVE to ACTIVE | TransplantCenter |
| POST | `/candidates/{id}/remove` | Remove candidate (LISTED to REMOVED) | TransplantCenter |
| POST | `/candidates/{id}/clinical-scores` | Create a DRAFT clinical score for a candidate | TransplantCenter |
| GET | `/candidates/{id}/clinical-scores` | List a candidate's clinical scores | UNOSAdmin, TransplantCenter |
| GET | `/clinical-scores/{id}` | Fetch a clinical score | UNOSAdmin, TransplantCenter |
| POST | `/clinical-scores/{id}/finalize` | Finalize a score (DRAFT to FINALIZED); computes MELD-Na or PELD | TransplantCenter |
| GET | `/candidates/{id}/registrations` | List a candidate's waitlist registrations | UNOSAdmin, TransplantCenter, OrganProcurementOrg |
| POST | `/donor-organs` | Register a recovered donor organ (AVAILABLE) | OrganProcurementOrg |
| GET | `/donor-organs` | List donor organs; filter by opo_id/organ_type/status | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| GET | `/donor-organs/{id}` | Fetch a donor organ | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| POST | `/donor-organs/{id}/discard` | Discard an organ (AVAILABLE/MATCHING to DISCARDED) | OrganProcurementOrg |
| POST | `/donor-organs/{id}/offer-next` | Issue an offer to the next-ranked eligible candidate | OrganProcurementOrg |
| POST | `/match-runs` | Run allocation policy for a donor organ (AVAILABLE to MATCHING) | OrganProcurementOrg |
| GET | `/match-runs/{id}` | Fetch a match run | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| GET | `/match-runs` | List match runs; filter by donor_organ_id/status | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| GET | `/match-runs/{id}/entries` | List a run's ranked entries | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| GET | `/match-list-entries/{id}` | Fetch a single match-list entry | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| GET | `/match-list-entries` | List match-list entries; filter by candidate_id/match_run_id | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| POST | `/offers` | Issue an offer to a specific candidate from a run | OrganProcurementOrg |
| GET | `/offers/{id}` | Fetch an offer | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| GET | `/offers` | List offers; filter by donor_organ_id/candidate_id/match_run_id/status | UNOSAdmin, OrganProcurementOrg, TransplantCenter |
| POST | `/offers/{id}/accept` | Accept an offer (OFFERED to ACCEPTED); cascades allocation | TransplantCenter |
| POST | `/offers/{id}/decline` | Decline an offer (OFFERED to DECLINED) | TransplantCenter |
| POST | `/offers/{id}/expire` | Expire an offer past its deadline (OFFERED to EXPIRED) | OrganProcurementOrg |
| POST | `/transplants` | Record a transplant from an accepted offer | TransplantCenter |
| GET | `/transplants/{id}` | Fetch a transplant | UNOSAdmin, TransplantCenter |
| GET | `/transplants` | List transplants; filter by candidate_id/donor_organ_id/offer_id | UNOSAdmin, TransplantCenter, OrganProcurementOrg |
| POST | `/transplants/{id}/mark-graft-failed` | Mark graft FAILED (AT_RISK to FAILED) | TransplantCenter |
| POST | `/transplants/{id}/follow-ups` | Schedule a follow-up for a transplant | TransplantCenter |
| GET | `/transplants/{id}/follow-ups` | List a transplant's follow-ups | UNOSAdmin, TransplantCenter |
| GET | `/follow-ups/{id}` | Fetch a follow-up | UNOSAdmin, TransplantCenter |
| POST | `/follow-ups/{id}/complete` | Complete a follow-up (SCHEDULED to COMPLETED) | TransplantCenter |
| POST | `/follow-ups/{id}/mark-missed` | Mark a follow-up MISSED (SCHEDULED to MISSED) | TransplantCenter |
| POST | `/unos-reports` | Submit a UNOS report | TransplantCenter |
| GET | `/unos-reports/{id}` | Fetch a UNOS report | UNOSAdmin, TransplantCenter |
| GET | `/unos-reports` | List UNOS reports; filter by transplant_id/candidate_id | UNOSAdmin, TransplantCenter |
| POST | `/unos-reports/{id}/accept` | Accept a report (SUBMITTED to ACCEPTED) | UNOSAdmin |
| POST | `/unos-reports/{id}/reject` | Reject a report (SUBMITTED to REJECTED) | UNOSAdmin |
| POST | `/_clock/set_current_utc` | Set the deterministic system clock (test-driving) | UNOSAdmin |
| GET | `/_clock` | Read the deterministic system clock | UNOSAdmin, TransplantCenter, OrganProcurementOrg |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ORGAN_VERSION` | 412 |
| `ERR_NO_FINALIZED_SCORE` | 409 |
| `ERR_CANDIDATE_NOT_ACTIVE` | 409 |
| `ERR_ABO_INCOMPATIBLE` | 409 |
| `ERR_POSITIVE_CROSSMATCH` | 409 |
| `ERR_SIZE_INCOMPATIBLE` | 409 |
| `ERR_OFFER_WINDOW_CLOSED` | 409 |
| `ERR_OFFER_WINDOW_OPEN` | 409 |
| `ERR_ISCHEMIA_WINDOW_CLOSED` | 409 |
| `ERR_DUPLICATE_OPEN_OFFER` | 409 |
| `ERR_NO_NEXT_CANDIDATE` | 409 |
| `ERR_OFFER_NOT_ACCEPTED` | 409 |
| `ERR_FOLLOWUP_BEFORE_TRANSPLANT` | 422 |
| `ERR_REPORT_SUBJECT_INVALID` | 422 |
| `ERR_ORGAN_TYPE_MISMATCH` | 409 |
