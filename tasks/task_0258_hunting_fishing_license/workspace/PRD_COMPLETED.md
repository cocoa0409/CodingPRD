# Hunting & Fishing License API — Product Requirements Document

## 1. Introduction

State fish-and-game agencies operate a tangle of overlapping regulatory programs: a catalog of saleable licenses, tags, and stamps; residency rules that change a buyer's price and eligibility; a hunter-education prerequisite that gates certain products; limited-quota lottery draws that allocate scarce tags by accumulated preference; season windows with per-species bag limits; mandatory harvest reporting; and the everyday reality that paper credentials get lost, damaged, or stolen and must be reissued. This API is the system of record that ties those programs together so that an applicant, an over-the-counter sales agent, a draw administrator, and a field enforcement officer all act on one consistent view of who is eligible for what, at what price, and within which limits.

The central tension the system must resolve is allocation under scarcity combined with strict compliance. Limited tags are awarded by a lottery that ranks applicants by preference points accrued over years of unsuccessful entries, and that ranking — together with the cascade of license issuance and point resets it triggers — must be computed deterministically and exactly once per pool. At the same time, every issuance is subject to a stack of compliance gates (residency, education, minimum age, draw-only restrictions) that must be evaluated in a fixed order so that the reason a request is rejected is predictable and auditable. This document specifies the entities, the lifecycle of each, the calculations that price licenses and rank draw applicants, and the validation rules that protect the integrity of the harvest and the fairness of the draw.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they are acting. The system recognizes exactly four roles, spelled precisely as follows: `Applicant`, `LicenseAgent`, `DrawOfficer`, and `GameWarden`. A request that omits either header, or carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. A request that is well-authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`.

The four roles partition the work as follows. An `Applicant` is an individual who registers themselves, submits residency and education proofs, enters draws, holds licenses, and reports harvests — always against their own resources. A `LicenseAgent` is an over-the-counter sales agent who issues new licenses and processes replacements but does not configure the catalog, seasons, or draw pools. A `DrawOfficer` is the fish-and-game administrator who manages the product catalog and seasons, adjudicates residency and education submissions, configures draw pools, executes the lottery draw, and may also perform issuance and replacement administratively. A `GameWarden` is the field enforcement officer who adjudicates submitted harvest reports.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`, conceptually naming the applicant the request acts for (for example, the `applicant_id` carried on a draw application or the holder of a license); the value is recorded for audit purposes only. Beyond the role-level access control of §4 (which role may invoke which operation), the system does not enforce per-applicant ownership: `X-User-ID` is never compared to a resource's applicant foreign key, so any authorized role — including an `Applicant` — may read or act on any resource regardless of whose applicant id it carries, and no ownership mismatch ever yields `ERR_UNAUTHORIZED`. When `X-User-Role` is `LicenseAgent`, `DrawOfficer`, or `GameWarden`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the total number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — `Applicant`, `ResidencyVerification`, `EducationCertificate`, `LicenseProduct`, `SpeciesSeason`, `DrawPool`, `DrawApplication`, `License`, `HarvestReport`, and `Replacement` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 when the resource is created and increments by one with every mutation (so the first mutation makes it 2); it is the basis for optimistic concurrency control where that applies.

These derived fields are true mutations: when the system writes a computed value onto a resource — for example, when an approved residency verification sets an applicant's residency standing, or when a draw resets an applicant's accumulated preference — the affected resource's `updated_at` is refreshed and its `version` is incremented by one, exactly as a client-initiated change would be.

### 2.5. Nested Reference Resolution and Existence Ordering

This API uses a flat resource topology: collections are addressed by their own identifier, and relationships between entities are carried as foreign-key fields in request bodies rather than as nested URL segments. Consequently, existence validation proceeds by reading identifiers left to right — first any identifier embedded in the request path, then each foreign-key reference in the request body in the order it is described. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later reference is examined and before any business rule is evaluated.

### 2.6. Validation Ordering and Precedence

When several checks could reject a single request, they are evaluated in a fixed precedence so that the surfaced error is deterministic. Authentication is checked first: a missing or malformed `X-User-ID`/`X-User-Role` pair yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Existence is checked third, per §2.5, yielding `ERR_NOT_FOUND`. Fourth comes state validity — whether the target resource is in a state from which the requested transition is defined — yielding `ERR_INVALID_STATE`. Fifth, on the draw-execution endpoint only, comes the optimistic-concurrency check described in §2.7, yielding `ERR_STALE_POOL_VERSION`. After these come the domain-specific business rules, whose relative ordering is described in §3 alongside the workflows they guard. Field-level request validation — required fields present, enum values legal, numeric fields within their declared bounds — is the lowest-priority check and yields `ERR_INVALID_REQUEST`; it is described as the final gate so that more meaningful conflicts surface ahead of generic malformation when both could apply, except where an earlier reference cannot even be resolved.

### 2.7. Optimistic Concurrency on Draw Execution

Executing a lottery draw is the one operation in this system that requires an optimistic-concurrency token. A request to execute the draw on a pool must carry the field `expected_draw_pool_version`, which is the `version` of the target `DrawPool` that the officer last observed; this field is not optional on that endpoint. As an exception to the §2.6 precedence (under which field-level validation is the lowest-priority gate), the presence and integer shape of `expected_draw_pool_version` are validated up front on this endpoint: a request that omits it or supplies a non-integer is rejected with `ERR_INVALID_REQUEST` before the existence and state checks run, so this malformation surfaces even when the path pool does not exist or is not `CLOSED`. Once the field is well-formed, the remaining checks follow the normal precedence below. The server compares it to the pool's current `version`. If another writer has already advanced the pool's `version` while it is still in a state from which execution is defined — that is, while the pool remains `CLOSED` — so that the supplied `expected_draw_pool_version` no longer matches the current `version`, the comparison fails and the request is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412) on the stale-version check, before any application is ranked or any tag is awarded. Because the stale-version check is fifth in precedence, after the fourth-priority state-validity check (§2.6), it is reached only when the pool is `CLOSED`: a re-execution attempt against a pool that a prior execution has already moved to `DRAWN` is not in a state from which execution is defined and is therefore rejected with `ERR_INVALID_STATE` (the fourth-priority check), regardless of whether the carried version is stale. No other endpoint in the system accepts or requires a version field in its request body.

### 2.8. Monetary Precision and Score Precision

All monetary amounts in this system are expressed as whole integer cents; there are no fractional cents and no currency strings. Where a price calculation introduces a fractional result — specifically the non-resident multiplier described in §3.5 — the rounding method is round half up, applied exactly once and at the point the specification names, never re-rounded downstream. Counts and scores that the system computes — preference points, priority scores, harvested quantities, and bag budgets — are integers with no rounding applied.

### 2.9. The Logical Clock

Several rules in this system depend on the current time: minimum-age computation on the issuance date, the entry deadline of a draw pool, and whether a harvest datetime falls inside an open season. To make these deterministic, the system reads the current instant from a server-controlled logical clock rather than wall-clock time. A `DrawOfficer` may set this clock by supplying the target instant in a `to_iso8601` field (which must parse as an ISO 8601 datetime, else `ERR_INVALID_REQUEST`); every subsequent reading of "now" — for deadline, season-window, and age evaluation — uses that instant until it is set again. The set-clock endpoint returns `200 OK` with a `data` object of the single field `current_utc` echoing the instant just set; it does not return a persisted resource and so carries none of the common system fields.

## 3. Business Logic & Workflows

### 3.1. Registering Applicants and Establishing Residency

The lifecycle begins when an `Applicant` (or a `DrawOfficer` acting administratively) registers a person by supplying their `full_name`, their `birth_date` as an ISO 8601 calendar date in `YYYY-MM-DD` form, and the `declared_state_code` — the two-letter code of the state the person claims as their primary residence. These three are validated only as required, non-empty strings; the system does not enforce the `YYYY-MM-DD` shape of `birth_date` nor the two-letter length of `declared_state_code` at registration, storing whatever non-empty string is supplied. The registration may optionally include `bonus_points`, an administratively granted integer that must be zero or greater and defaults to 0 when omitted. On registration the system initializes the applicant's residency standing, held in `residency_status`, to `UNVERIFIED`; sets the hunter-education flag `education_certified` to false; and sets the accrued-preference counter `preference_points` to 0. The values of `residency_status`, `education_certified`, and `preference_points` are all system-computed and never accepted directly from the client.

Residency is established by submitting a `ResidencyVerification`. The submission names the `applicant_id` it proves residency for, the `proof_type` — one of `DRIVERS_LICENSE`, `UTILITY_BILL`, `TAX_RECORD`, or `TRIBAL_ID` — the `proof_state_code` shown on that document, and `continuous_months`, the number of continuous months of domicile the proof attests, which must be zero or greater. A new verification begins in `PENDING` status with its `resulting_residency` not yet determined.

A `DrawOfficer` adjudicates a pending verification. Adjudication is defined only from the `PENDING` state; attempting it on an already-resolved verification is an `ERR_INVALID_STATE` conflict. On approval, the verification moves `PENDING → APPROVED` and the system computes `resulting_residency`: the result is `RESIDENT` when the `proof_state_code` matches the applicant's `declared_state_code` and `continuous_months` is at least the residency threshold of twelve continuous months, and is `NONRESIDENT` otherwise. The computed `resulting_residency` is then written onto the applicant as their new `residency_status`, and the applicant's `version` is incremented. On denial, the verification moves `PENDING → DENIED` and the applicant's `residency_status` is left unchanged.

### 3.2. The Hunter-Education Prerequisite

Hunter education is tracked separately from residency. An `Applicant` (or a `DrawOfficer`) submits an `EducationCertificate` naming the `applicant_id`, the `course_code` of the completed hunter-education course, and the `completion_date` as an ISO 8601 date. The certificate begins in `PENDING` status.

A `DrawOfficer` reviews the certificate, an action defined only from `PENDING`; attempting it otherwise yields `ERR_INVALID_STATE`. Verifying it moves the certificate `PENDING → VERIFIED`, sets the applicant's `education_certified` flag to true, and increments the applicant's `version`. Rejecting it moves the certificate `PENDING → REJECTED` and leaves `education_certified` unchanged. An applicant's `education_certified` is true precisely when at least one of their certificates has reached `VERIFIED`; this flag is the gate that certain products consult before they may be issued, as described in §3.7.

### 3.3. Building the Catalog: Products

A `DrawOfficer` maintains the catalog of saleable items. Creating a `LicenseProduct` requires a `sku` (the catalog stock-keeping unit), a `product_kind` that is one of `LICENSE`, `TAG`, or `STAMP`, and a `base_fee_cents` resident base price that must be zero or greater. Optionally the officer supplies a `species_season_id` binding the product to a particular season ruleset (left null for general licenses and stamps), a `requires_education` boolean defaulting to false, a `residency_restriction` that is one of `ANY`, `RESIDENT_ONLY`, or `NONRESIDENT_ONLY` and defaults to `ANY`, and a `min_age_years` minimum age in whole years that must be zero or greater and defaults to 0. A new product is `ACTIVE`. The `sku` must be unique among products that are currently `ACTIVE`; creating a product whose `sku` collides with an existing `ACTIVE` product is rejected with `ERR_DUPLICATE_SKU`.

A `DrawOfficer` may retire a product, moving its `status` to `RETIRED`. Retirement records this status but is not otherwise enforced: it is not state-guarded (retiring a product in any current status, including one already `RETIRED`, simply sets `status` to `RETIRED`, refreshes `updated_at`, and increments `version`), and issuance — whether over the counter or at draw award — does not consult the product's `status`, so licenses may still be minted from a `RETIRED` product. Retirement does not affect licenses already issued.

### 3.4. Defining Seasons, Bag Limits, and the Draw Pool

A `DrawOfficer` defines a `SpeciesSeason` by supplying the regulated `species`, the `season_open` instant (ISO 8601 UTC, inclusive), the `season_close` instant (ISO 8601 UTC, exclusive — so an admissible harvest instant is one at or after the open instant and strictly before the close instant), and the `bag_limit`, the maximum total quantity an applicant may harvest in this season, which must be zero or greater. The officer may also set `draw_required`, a boolean defaulting to false; when true, a tag for this season may be obtained only by winning a draw and may never be sold over the counter. A season is created in `DRAFT`, is moved to `OPEN` by the officer (a transition `DRAFT → OPEN` defined only from `DRAFT`), and is later moved to `CLOSED` (a transition `OPEN → CLOSED` defined only from `OPEN`); attempting either out of order yields `ERR_INVALID_STATE`. Harvest reporting requires the bound season to be `OPEN`.

A limited-tag lottery is configured as a `DrawPool`. The officer supplies the `species_season_id` whose tags the pool allocates, the `license_product_id` of the `TAG` product awarded to winners, the `quota` of tags available (zero or greater), the `entry_deadline` (ISO 8601 UTC) after which entries are refused, and optionally the `scoring_model`, which is one of `SQUARED` or `LINEAR` and defaults to `SQUARED`. A new pool is in `ACCEPTING` status with its `awarded_count` initialized to 0. The pool also carries a `version` that participates in the concurrency check of §2.7. The pool advances `ACCEPTING → CLOSED` when the officer closes entries — defined only while the pool is `ACCEPTING` and only once the clock is at or past the pool's `entry_deadline` — and finally `CLOSED → DRAWN` when the draw is executed. On the close-entries action the `ACCEPTING` state requirement is checked first and a pool not in `ACCEPTING` is rejected with `ERR_INVALID_STATE`; the deadline requirement is checked next, and attempting to close while the clock is still strictly before `entry_deadline` is likewise rejected with `ERR_INVALID_STATE`.

### 3.5. Pricing a License

The price a holder pays, recorded as `fee_charged_cents`, is computed whenever a license is minted — over the counter, at draw award, or as a replacement — from a single product and the issuing applicant's residency standing at issuance time. The calculation has a fixed two-step order: the residency multiplier is applied first, and the over-the-counter agent surcharge second.

Before any pricing, the residency restriction is enforced: if the product's `residency_restriction` is `RESIDENT_ONLY` and the applicant's `residency_status` is not `RESIDENT`, or if the restriction is `NONRESIDENT_ONLY` and the applicant's `residency_status` is not `NONRESIDENT`, the issuance is rejected with `ERR_RESIDENCY_RESTRICTED`. Otherwise pricing begins from the product's `base_fee_cents`. For a resident applicant the base is taken as-is. For a non-resident applicant the base is multiplied by the non-resident multiplier of 2.5 and that product is rounded half up to whole cents — this rounding happens here, before any surcharge. Then, and only when the license is being issued over the counter, a flat agent surcharge of 300 cents is added to the priced amount. The resulting amount is the `fee_charged_cents`. Because the multiply-then-round happens strictly before the additive surcharge, a resident and a non-resident buying the same product over the counter diverge in price by more than a flat offset.

### 3.6. Entering and Withdrawing from a Draw

An `Applicant` (or a `DrawOfficer`) enters a draw by creating a `DrawApplication` that names the `draw_pool_id` of the pool to compete in and the `applicant_id` entering. At submission the system freezes two values onto the application: `points_at_entry`, a snapshot of the applicant's current `preference_points`, and `bonus_at_entry`, a snapshot of the applicant's current `bonus_points`. These frozen snapshots — not the live applicant values — are what the draw later scores. The application also carries `priority_score`, initialized to 0 and computed at draw time, and `issued_license_id`, which stays null until and unless the application is awarded a tag. A new application is in `SUBMITTED` status.

Entry is gated by two business rules layered on top of existence and state checks. First, an application may be created only while the pool is `ACCEPTING` and the clock is strictly before the pool's `entry_deadline`; an attempt once the pool is no longer accepting or the deadline has arrived is rejected with `ERR_ENTRY_CLOSED`. Second, an applicant may hold at most one application per pool that has not been withdrawn; a second entry by the same applicant into the same pool is rejected with `ERR_DUPLICATE_ENTRY`. These two are evaluated in that order — the entry-window check (`ERR_ENTRY_CLOSED`) before the duplicate-entry check (`ERR_DUPLICATE_ENTRY`).

An `Applicant` may withdraw their own application before the draw runs (a `DrawOfficer` may do so as well). Withdrawal moves the application `SUBMITTED → WITHDRAWN` and changes no preference points. It is permitted only when the application is still `SUBMITTED` and the pool is still `ACCEPTING`; once entries have closed the application can no longer be withdrawn, and an out-of-state attempt yields `ERR_INVALID_STATE`.

### 3.7. Issuing a License Over the Counter

A `LicenseAgent` (or a `DrawOfficer`) issues a license over the counter by naming the `applicant_id` and the `license_product_id`. The minted `License` records its `applicant_id`, its `license_product_id`, an `issued_via` of `OVER_THE_COUNTER`, the computed `fee_charged_cents` from §3.5, and a `status` of `ISSUED`. Its `draw_application_id` is null for over-the-counter issuance, and `superseded_by_id` is null while the license is `ISSUED`.

Over-the-counter issuance is guarded by a stack of compliance checks evaluated in a fixed order after existence is confirmed. First, the draw-only rule: a `TAG` product bound to a season whose `draw_required` is true may not be sold over the counter at all and is rejected with `ERR_DRAW_REQUIRED` — such a tag must instead arrive carrying a draw application reference. Second, the education prerequisite: if the product's `requires_education` is true and the applicant's `education_certified` is not true, the issuance is rejected with `ERR_EDUCATION_REQUIRED`. Third, the minimum-age rule: the applicant's age in whole years on the issuance date, computed from `birth_date` against the current clock, must be at least the product's `min_age_years`; a younger applicant is rejected with `ERR_MINIMUM_AGE`. Fourth, the residency restriction of §3.5 (`ERR_RESIDENCY_RESTRICTED`). Only after all four pass does pricing complete and the license get created.

### 3.8. Executing the Draw

When the `entry_deadline` has passed, a `DrawOfficer` first closes the pool's entries, then executes the draw. Execution is defined only when the pool is `CLOSED`; otherwise it is an `ERR_INVALID_STATE` conflict. It additionally requires that the bound `SpeciesSeason` be `OPEN` at execution time, and it requires the optimistic-concurrency token of §2.7: the supplied `expected_draw_pool_version` must equal the pool's current `version`, or the request is rejected with `ERR_STALE_POOL_VERSION` before any award.

Execution is a single atomic transaction with a branching, multi-level cascade. The system first computes a `priority_score` for every `SUBMITTED` application in the pool from its frozen snapshots: let the application's `points_at_entry` be its preference contribution and `bonus_at_entry` its bonus contribution. Under the `SQUARED` model the score is the preference points multiplied by themselves, plus the bonus points. Under the `LINEAR` model the score is the preference points plus the bonus points. (Concretely, three preference points and two bonus points yield eleven under `SQUARED` but five under `LINEAR`.) The system then ranks the submitted applications by `priority_score` from highest to lowest, breaking ties by `created_at` from earliest to latest — never by identifier.

The top applications up to the pool's `quota` are awarded: each moves `SUBMITTED → AWARDED`, and this fork drives a deeper cascade. For each awarded application the system mints a `License` with `issued_via` of `DRAW_AWARD` (priced per §3.5 using the applicant's residency at award time, with no agent surcharge), populates the application's `issued_license_id` with that license, resets the applicant's `preference_points` to 0, and increments the applicant's `version`. Every remaining `SUBMITTED` application that did not place within quota moves `SUBMITTED → UNSUCCESSFUL`; for each, the applicant's `preference_points` is increased by one — but clamped so it never exceeds the preference-point cap of twelve — and the applicant's `version` is incremented. The mirror symmetry here is exact: awarded entries reset the holder's points to zero, unsuccessful entries add one capped point, and both bump the holder's version. Finally the pool's `awarded_count` is set to the number of awarded applications, the pool moves `CLOSED → DRAWN`, and the pool's `version` is incremented by one as the concurrency advance.

### 3.9. Harvest Reporting and the Bag Budget

A harvest is reported by an `Applicant` (or a `DrawOfficer`) under a license by naming the `license_id`, the `harvest_datetime` (ISO 8601 UTC), and the `quantity` taken, which must be at least 1. The referenced license must be `ISSUED`. A new `HarvestReport` is in `SUBMITTED` status and immediately counts against the season's bag budget.

Two business gates protect the harvest, both evaluated against the season bound to the license's product through its `species_season_id`. First, the season-window rule: the `harvest_datetime` must fall within the bound season's window — at or after `season_open` and strictly before `season_close` — and the season must be `OPEN` at report time; a violation of either is rejected with `ERR_SEASON_NOT_OPEN`. If the license's product is not bound to any season at all, the season-window rule cannot be satisfied and the report is likewise rejected with `ERR_SEASON_NOT_OPEN`. Second, the bag-limit rule: the season bag budget counts the summed `quantity` of all harvest reports filed under the applicant's licenses for that season whose status is `SUBMITTED` or `ACCEPTED` (reports in `REJECTED` are excluded and do not count). A new report of some quantity is admissible only when the already-counted quantity plus that new quantity does not exceed the season's `bag_limit`; otherwise it is rejected with `ERR_BAG_LIMIT_EXCEEDED`. The season-window check is evaluated before the bag-limit check.

The remaining bag budget for a license's season may be read directly; the computed read returns a plain `data` object (not a persisted resource, so it carries none of the common system fields) holding the bound `season_id`, the season's `bag_limit`, the `counted` quantity (the `SUBMITTED`-plus-`ACCEPTED` sum defined above), and the `remaining` quantity, which is the `bag_limit` minus the `counted` amount. When the license's product is not bound to any season, the read returns `season_id` null with `bag_limit`, `counted`, and `remaining` all 0.

A `GameWarden` adjudicates a submitted report, an action defined only from `SUBMITTED`; otherwise `ERR_INVALID_STATE`. Accepting it moves the report `SUBMITTED → ACCEPTED`, and its quantity remains counted against the bag budget. Rejecting it moves the report `SUBMITTED → REJECTED` and releases its quantity from the budget so that it no longer counts. These two adjudication branches are symmetric: accept keeps the quantity counted, reject releases it.

### 3.10. Replacing a Lost, Damaged, or Stolen Credential

When a credential is lost, damaged, or stolen, a `LicenseAgent` (or a `DrawOfficer`) issues a `Replacement` by naming the `original_license_id` and the `reason`, which is one of `LOST`, `DAMAGED`, or `STOLEN`. The original license must be `ISSUED`. A replacement is not a re-purchase: the holder pays only the duplicate-issuance administrative fee recorded as `admin_fee_cents`, and the newly minted credential carries a `fee_charged_cents` of 0.

The administrative fee is computed from three inputs — the reason, the original product's kind, and the holder's residency — as follows. A stolen-credential replacement is fully waived: when the `reason` is `STOLEN`, the `admin_fee_cents` is 0 and no surcharges apply (this short-circuits the rest of the calculation). Otherwise the fee starts from a replacement base of 1500 cents; if the original product's `product_kind` is `TAG`, a tag-replacement surcharge of 1000 cents is added; and if the holder's `residency_status` is `NONRESIDENT`, a non-resident replacement surcharge of 500 cents is added. The product kind is resolved through the original license's `license_product_id`, and the holder through the original license's `applicant_id`.

Issuing the replacement is a single atomic cascade. The system computes the `admin_fee_cents`, mints a replacement `License` for the same product and applicant — copying the original's `draw_application_id`, marking `issued_via` as `OVER_THE_COUNTER`, and setting its `fee_charged_cents` to 0 — and records that new license as the replacement's `replacement_license_id`. The original license is then voided: its `status` moves `ISSUED → VOIDED` and its `superseded_by_id` is set to the replacement license. Finally, the original's open harvest budget is preserved by re-linking: every `HarvestReport` filed under the original license that is still in `SUBMITTED` status is migrated to point at the replacement license, so that quantities already committed against the season continue to count under the new credential. The education prerequisite (`ERR_EDUCATION_REQUIRED`) and the residency restriction (`ERR_RESIDENCY_RESTRICTED`) apply to a replacement just as they do to a fresh issuance.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and the draw execution — return a `200 OK` status code. Read operations return `200 OK`. To reconstruct the full request body, response shape, and side effects of any endpoint below, refer to the corresponding workflow narrative in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/applicants` | Register a new applicant | `Applicant`, `DrawOfficer` |
| GET | `/applicants/{id}` | Fetch an applicant with computed standing | `Applicant`, `DrawOfficer`, `LicenseAgent`, `GameWarden` |
| GET | `/applicants` | List applicants | `DrawOfficer`, `LicenseAgent` |
| POST | `/residency-verifications` | Submit residency proof | `Applicant`, `DrawOfficer` |
| GET | `/residency-verifications/{id}` | Fetch a residency verification | `DrawOfficer`, `Applicant` |
| GET | `/residency-verifications` | List residency verifications | `DrawOfficer`, `Applicant` |
| POST | `/residency-verifications/{id}/approve` | Approve a residency verification | `DrawOfficer` |
| POST | `/residency-verifications/{id}/deny` | Deny a residency verification | `DrawOfficer` |
| POST | `/education-certificates` | Submit a hunter-education record | `Applicant`, `DrawOfficer` |
| GET | `/education-certificates/{id}` | Fetch an education certificate | `DrawOfficer`, `Applicant` |
| GET | `/education-certificates` | List education certificates | `DrawOfficer`, `Applicant` |
| POST | `/education-certificates/{id}/verify` | Verify an education certificate | `DrawOfficer` |
| POST | `/education-certificates/{id}/reject` | Reject an education certificate | `DrawOfficer` |
| POST | `/license-products` | Create a catalog product | `DrawOfficer` |
| GET | `/license-products/{id}` | Fetch a catalog product | `DrawOfficer`, `LicenseAgent`, `Applicant` |
| GET | `/license-products` | List catalog products | `DrawOfficer`, `LicenseAgent`, `Applicant` |
| POST | `/license-products/{id}/retire` | Retire a product | `DrawOfficer` |
| POST | `/species-seasons` | Define a species season | `DrawOfficer` |
| GET | `/species-seasons/{id}` | Fetch a species season | `DrawOfficer`, `LicenseAgent`, `GameWarden`, `Applicant` |
| GET | `/species-seasons` | List species seasons | `DrawOfficer`, `LicenseAgent`, `GameWarden`, `Applicant` |
| POST | `/species-seasons/{id}/open` | Open a season | `DrawOfficer` |
| POST | `/species-seasons/{id}/close` | Close a season | `DrawOfficer` |
| POST | `/draw-pools` | Create a draw pool | `DrawOfficer` |
| GET | `/draw-pools/{id}` | Fetch a draw pool | `DrawOfficer`, `Applicant` |
| GET | `/draw-pools` | List draw pools | `DrawOfficer`, `Applicant` |
| POST | `/draw-pools/{id}/close-entries` | Close pool entries | `DrawOfficer` |
| POST | `/draw-pools/{id}/execute-draw` | Execute the lottery draw | `DrawOfficer` |
| POST | `/draw-applications` | Enter an applicant into a pool | `Applicant`, `DrawOfficer` |
| GET | `/draw-applications/{id}` | Fetch a draw application | `DrawOfficer`, `Applicant` |
| GET | `/draw-applications` | List draw applications | `DrawOfficer`, `Applicant` |
| POST | `/draw-applications/{id}/withdraw` | Withdraw a draw application | `Applicant`, `DrawOfficer` |
| POST | `/licenses` | Issue an over-the-counter license | `LicenseAgent`, `DrawOfficer` |
| GET | `/licenses/{id}` | Fetch a license | `DrawOfficer`, `LicenseAgent`, `GameWarden`, `Applicant` |
| GET | `/licenses` | List licenses | `DrawOfficer`, `LicenseAgent`, `GameWarden`, `Applicant` |
| GET | `/licenses/{id}/bag-budget` | Read remaining bag budget for a license's season | `DrawOfficer`, `GameWarden`, `Applicant` |
| POST | `/harvest-reports` | Report a harvest | `Applicant`, `DrawOfficer` |
| GET | `/harvest-reports/{id}` | Fetch a harvest report | `DrawOfficer`, `GameWarden`, `Applicant` |
| GET | `/harvest-reports` | List harvest reports | `DrawOfficer`, `GameWarden`, `Applicant` |
| POST | `/harvest-reports/{id}/accept` | Accept a harvest report | `GameWarden` |
| POST | `/harvest-reports/{id}/reject` | Reject a harvest report | `GameWarden` |
| POST | `/replacements` | Issue a duplicate/replacement | `LicenseAgent`, `DrawOfficer` |
| GET | `/replacements/{id}` | Fetch a replacement record | `DrawOfficer`, `LicenseAgent`, `Applicant` |
| GET | `/replacements` | List replacements | `DrawOfficer`, `LicenseAgent`, `Applicant` |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | `DrawOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_POOL_VERSION` | 412 Precondition Failed |
| `ERR_DRAW_REQUIRED` | 409 Conflict |
| `ERR_EDUCATION_REQUIRED` | 409 Conflict |
| `ERR_MINIMUM_AGE` | 409 Conflict |
| `ERR_RESIDENCY_RESTRICTED` | 409 Conflict |
| `ERR_ENTRY_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_SEASON_NOT_OPEN` | 409 Conflict |
| `ERR_BAG_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
