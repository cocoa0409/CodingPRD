# Community Resource Directory API — Product Requirements Document

## 1. Introduction

Community resource and social-services directories — the "211" hotlines and "findhelp" platforms that route residents to food, housing, healthcare, mental-health, employment, transport, legal-aid, and childcare services — sit at the intersection of three groups that rarely share a database: the caseworkers doing intake, the community-based providers delivering services, and the funders underwriting completion costs. Today, when a caseworker screens a family for a food-security program, the caseworker often cannot see whether the program has open slots this week, whether the client's home is within a reasonable transit time of the pantry, whether the funder's grant still has room, or whether the family's earlier consent to share information with that provider has expired. The result is guesswork, duplicate referrals, and closed-loop follow-ups that never actually close.

This document specifies a directory API that closes that loop end-to-end. Providers publish programs with eligibility criteria, capacity, availability windows, accessibility features, and supported languages. Caseworkers register clients, capture presenting needs and urgency in a screening intake, and — under a client-signed consent grant — dispatch referrals that carry a computed eligibility score, a provisional cost estimate, and two independent travel-burden estimates for the client's chosen transport mode. Providers accept, start, and complete service; caseworkers or provider staff then file an outcome report that debits the funder's grant. Funders receive periodic reports aggregating outcomes across programs, with a caller-selected rounding order so that "per-referral rounding then sum" and "sum then final rounding" can both be attested to. The whole system runs on a logical clock so consent expiry, availability-window comparisons, and fiscal-year rollovers are deterministic under test.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying which of the five roles the caller is asserting. If either header is missing or unrecognised the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present but the asserted role is not permitted for the endpoint the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five recognised roles, spelled exactly as they must appear in `X-User-Role`, are:

- `PlatformAdmin` — the system operator with unrestricted access to registration, patching, funder-report generation, outcome reversal, and the logical-clock control endpoint. `X-User-ID` for a `PlatformAdmin` is an opaque operator identifier not tied to any persisted entity; the server may record it in audit trails but does not compare it to any entity's `id`.
- `Caseworker` — the community caseworker who registers clients, screens intakes, files referrals, and manages transport plans. `X-User-ID` for a `Caseworker` is likewise an opaque operator identifier not tied to any persisted entity.
- `ProviderStaff` — a member of a provider organisation acting on that provider's own programs. When `X-User-Role` is `ProviderStaff`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` (a program, one of its availability windows, or a referral targeting one of its programs) compare the resource's provider foreign key to `X-User-ID`.
- `Client` — the individual receiving services. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` (an intake, a consent grant, a referral through its intake, or the client record itself) compare the resource's client foreign key to `X-User-ID`.
- `FunderReporter` — a funder-side viewer of that funder's own reports. When `X-User-Role` is `FunderReporter`, `X-User-ID` is the `id` of the acting `Funder`; ownership checks compare the funder foreign key on a funder record, funder report, or (transitively) an outcome report's program to `X-User-ID`.

For any endpoint whose authorised roles list includes an entity-backed role (`ProviderStaff`, `Client`, or `FunderReporter`), a caller whose asserted role passes the role-membership check but whose `X-User-ID` does not match the resource-owner foreign key on the target is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0 and must be at least 0. List endpoints always sort results by `created_at` in ascending order. Every list response echoes back the effective `limit` and `offset` in `meta`, along with `total_count` (the total number of records matching the query, before the limit/offset window is applied) and `has_more` (true when additional records remain beyond the current window).

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted UUID `id` (a plain UUID string with no type prefix), plus a `created_at` timestamp fixed at resource creation. Most resources — every entity in this system except `FunderReport` — also carry an `updated_at` timestamp that is refreshed on every server-side mutation and an integer `version` counter that starts at 1 on creation and increments by exactly 1 on every mutation. `FunderReport` is a computed, immutable aggregate; it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from its representation. All timestamps in the system — `created_at`, `updated_at`, `granted_at`, `expires_at`, `start_ts`, `end_ts`, `pickup_start_ts`, `pickup_end_ts`, `reporting_period_start`, `reporting_period_end` — are ISO 8601 UTC strings with three fractional-second digits.

### 2.5. Nested Resource Path Validation

Endpoints that address a nested resource carry the parent identifier in the URL path (for example, an intake's referral list lives under the intake's own path, and an availability window's list lives under the program's path). Path parameters are resolved left-to-right: the parent entity is looked up first, and if it does not exist the request is rejected with the parent's own not-found error (`ERR_FUNDER_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_CONSENT_GRANT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, or `ERR_OUTCOME_REPORT_NOT_FOUND`, each returning HTTP 404) before any body validation runs. Body-referenced foreign keys — such as `provider_id` and `funder_id` when creating a program, `provider_id` when creating a consent grant, or `program_id` and `consent_grant_id` when creating a referral — are validated after path resolution; any body foreign key that fails to resolve is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Optimistic Concurrency Control

Program edits are guarded by optimistic concurrency. When a client patches a program, the request body must include a non-optional `expected_program_version` field carrying the value of `version` the client last observed on that program. The server compares `expected_program_version` to the program's current `version`. If another writer has advanced the program's version since the client last read it — whether by an explicit patch or by a cascaded referral state change that bumped `capacity_slots_taken` and therefore `version` — the patch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), preventing the client from overwriting a program state it has not observed. Every other write endpoint in the system does not carry a version field; only program patch is version-guarded.

### 2.7. Program Postures — Two Independent Parallel Dimensions

Each `Program` carries two enumerated postures that evolve on independent axes. The first, `intake_posture`, takes one of the exact values `OPEN`, `RESTRICTED`, or `CLOSED`, and is a system-recomputed reflection of current capacity utilisation (see §2.8 and §3.4). The second, `funder_reporting_posture`, takes one of the exact values `OPEN`, `LOCKED`, or `ARCHIVED`, and reflects whether outcomes on this program are still eligible for inclusion in a fresh funder report. The two postures move independently: a program can be `intake_posture` `CLOSED` while its `funder_reporting_posture` remains `OPEN`, and vice versa.

`funder_reporting_posture` starts at `OPEN` when the program is created. When a funder report is generated that covers at least one outcome report tied to this program, the program's `funder_reporting_posture` advances from `OPEN` to `LOCKED` and `version` is incremented by 1. When the logical clock later crosses the funder's fiscal-year rollover — the moment the clock's month equals the funder's `fiscal_year_start_month` and the day is 1 — every program locked to that funder advances from `LOCKED` to `ARCHIVED` and `version` is again incremented by 1. `ARCHIVED` is terminal for the current fiscal cycle; the system does not model resetting `funder_reporting_posture` back to `OPEN` for a new fiscal year.

### 2.8. Financial, Precision, and Reporting Principles

All monetary quantities are stored as whole cents in integer fields — `unit_cost_cents`, `eligibility_income_max_cents`, `monthly_income_cents`, `grant_cents_total`, `grant_cents_remaining`, `cost_cents`, `provisional_cost_cents`, `service_cost_final_cents`, and `total_disbursement_cents` — so no rounding is ever performed on inputs. Any calculation whose intermediate result is fractional is rounded to whole cents using round-half-up; the two travel-burden minute figures on a referral are similarly rounded to 2 decimal places using round-half-up, and the eligibility score is rounded to 2 decimal places using round-half-up. `reporting_currency` is a per-funder currency label taking one of the exact values `USD`, `CAD`, or `EUR`; it is applied uniformly to every line item in that funder's reports and to the funder's `grant_cents_total` and `grant_cents_remaining`.

A funder's `grant_cents_remaining` is maintained as a running ledger: it equals `grant_cents_total` minus the sum of `service_cost_final_cents` across every outcome report whose status is `ACTIVE` and whose referral's program is underwritten by this funder. Filing a new outcome report debits `grant_cents_remaining` by the newly computed `service_cost_final_cents`; reversing an active outcome report credits `grant_cents_remaining` by exactly the same integer-cents value. The invariant is that, after any (create, reverse) pair on the same outcome report, `grant_cents_remaining` returns to the exact integer-cents value it held before the create.

### 2.9. Temporal Semantics — Logical Clock, Half-Open and Closed-Closed Intervals

The system maintains a server-wide logical clock rather than reading wall-clock time. At server startup the logical clock is fixed at exactly `2026-03-01T00:00:00Z`, and any temporal comparison — consent expiry, availability-window ordering, transport-plan buffers, fiscal-year rollover, current-clock-date derivation for age computation — reads that logical clock and no other. An administrative capability advances the clock to a supplied ISO 8601 UTC instant provided in the `to_iso8601` field. When the clock advances, two families of system transitions fire: every `GRANTED` `ConsentGrant` whose `expires_at` is less than or equal to the new clock is transitioned to `EXPIRED`, and every `LOCKED` program whose funder's fiscal-year rollover falls between the old clock and the new clock is transitioned from `LOCKED` to `ARCHIVED`.

Availability windows on a program use a half-open interval `[start_ts, end_ts)` — the start is inclusive, the end is exclusive — so two windows overlap when the first window's start is strictly before the second window's end and the second window's start is strictly before the first window's end; two adjacent windows where one window's `end_ts` equals the next window's `start_ts` do not overlap. Transport plans use the opposite convention: `[pickup_start_ts, pickup_end_ts]` is a closed-closed interval where both endpoints are inclusive, and separation between two plans is measured in seconds between the closing endpoint of one interval and the opening endpoint of the other (see §3.6).

### 2.10. Validation Priority and Ordering

Validations across the API are evaluated in a fixed priority order so that failure modes are surfaced deterministically. Authentication (`ERR_UNAUTHENTICATED`, HTTP 401) is evaluated first, then role permission for the endpoint (`ERR_UNAUTHORIZED`, HTTP 403), then existence checks on every entity referenced in the URL path (in path order: funder, provider, program, client, intake, consent grant, referral, outcome report — each returning its own not-found error at HTTP 404). Body foreign-key resolution (`ERR_INVALID_REQUEST`, HTTP 400) comes next, followed by ownership matching for entity-backed roles (`ERR_OWNERSHIP_VIOLATION`, HTTP 403). Only after these gates have passed does the server evaluate state preconditions (the endpoint-specific `ERR_*_INVALID_STATE`, `ERR_INTAKE_NOT_DRAFT`, `ERR_INTAKE_NOT_SCREENED`, `ERR_REFERRAL_INVALID_STATE`, `ERR_CONSENT_ALREADY_TERMINAL`, `ERR_OUTCOME_ALREADY_REVERSED`, `ERR_PROGRAM_CLOSED_TO_INTAKE`), then the domain-specific business rules described throughout §3, and finally, for `PATCH /programs/{id}`, the optimistic-concurrency stale-version check.

Within referral creation specifically, this priority ordering resolves ambiguity when a client is simultaneously ineligible in multiple ways: consent-shape rejection (`ERR_CONSENT_PROVIDER_MISMATCH`) surfaces before program-category mismatch (`ERR_PROGRAM_CATEGORY_MISMATCH`); category mismatch surfaces before the eligibility-score threshold (`ERR_ELIGIBILITY_BELOW_THRESHOLD`); the score check surfaces before age (`ERR_AGE_INELIGIBLE`), income (`ERR_INCOME_INELIGIBLE`), and program-full (`ERR_CAPACITY_EXHAUSTED`) checks in that same priority order. When a referral would fail multiple rules at once, the highest-priority applicable rule wins.

## 3. Business Logic & Workflows

### 3.1. Building the Directory: Funders, Providers, Programs, and Availability Windows

The directory is bootstrapped by a `PlatformAdmin`. Funders are registered with a legal `name`, an integer `fiscal_year_start_month` in the range 1 through 12 inclusive (the month a new fiscal year begins for reporting cadence), a non-negative integer `grant_cents_total` (the total grant budget for the current fiscal year, in whole cents), and a `reporting_currency` set to one of `USD`, `CAD`, or `EUR`. On creation, a funder's `grant_cents_remaining` is initialised equal to `grant_cents_total`.

Providers are registered with a `legal_name`, a service-address `location_lat` in the closed range from -90.0 to 90.0 decimal degrees and a `location_lng` in the closed range from -180.0 to 180.0 decimal degrees, an `accessibility_features` array (a subset of `WHEELCHAIR`, `HEARING_LOOP`, `ASL_INTERPRETER`, `LARGE_PRINT` describing the accommodations the provider offers on site), and a `languages_supported` array (a non-empty subset of `EN`, `ES`, `FR`, `ZH`, `VI`, `AR` naming the languages in which the provider can actually deliver service).

A program is created under an existing provider and an existing funder — both the body's `provider_id` and `funder_id` must resolve to persisted records, or the create is rejected with `ERR_INVALID_REQUEST`. Programs declare a primary `category` from one of `FOOD`, `HOUSING`, `HEALTHCARE`, `MENTAL_HEALTH`, `EMPLOYMENT`, `TRANSPORT`, `LEGAL_AID`, `CHILDCARE`, a monthly household-income ceiling `eligibility_income_max_cents` (non-negative integer cents; strictly greater client income is inelegible for the program), an inclusive age band described by `eligibility_age_min` and `eligibility_age_max` (each an integer from 0 to 120, with the maximum at least as large as the minimum), a per-completed-referral `unit_cost_cents` billed to the funder, and a `capacity_slots_total` of at least 1 which is the maximum number of concurrent referrals the program can hold across all three in-flight statuses `PROPOSED`, `ACCEPTED`, and `SERVICE_IN_PROGRESS`. At creation, the server initialises `capacity_slots_taken` to 0, `intake_posture` to `OPEN`, and `funder_reporting_posture` to `OPEN`.

Programs may be edited by a `PlatformAdmin` through a version-guarded patch. Patchable fields are `eligibility_income_max_cents`, `eligibility_age_min`, `eligibility_age_max`, `unit_cost_cents`, and `capacity_slots_total`. Every patch must include `expected_program_version`, and stale versions are rejected as described in §2.6; a successful patch increments `version` by 1 and refreshes `updated_at`.

Availability windows publish concrete time slots for a program. When adding a window, `start_ts` must be strictly greater than the current logical clock — a `start_ts` exactly equal to the clock is rejected as being in the past with `ERR_WINDOW_IN_PAST`. `end_ts` must be strictly greater than `start_ts`, and `max_slots` must be at least 1. The new window's half-open interval `[start_ts, end_ts)` must not overlap any existing window on the same program under the half-open semantics of §2.9; a violation is rejected with `ERR_WINDOW_OVERLAP`. In addition, the sum of `max_slots` across every availability window belonging to the program, including the new one, must not exceed the program's `capacity_slots_total`; exceeding it is rejected with `ERR_WINDOW_SLOTS_EXCEED_CAPACITY`.

### 3.2. Client Onboarding, Intake Screening, and the Revision Cycle

A caseworker (or a `PlatformAdmin`) registers a client with a `full_name`, a `date_of_birth` (an ISO 8601 date in `YYYY-MM-DD` form that must be strictly greater than `1900-01-01` and strictly less than the current logical clock date), a household `monthly_income_cents`, a home `home_lat` in the closed range from -90.0 to 90.0 and `home_lng` in the closed range from -180.0 to 180.0, a `preferred_language` from `EN`, `ES`, `FR`, `ZH`, `VI`, or `AR`, and an `accessibility_needs` array (a subset of `WHEELCHAIR`, `HEARING_LOOP`, `ASL_INTERPRETER`, `LARGE_PRINT` describing the accommodations the client requires).

Intake capture happens next. A caseworker (or `PlatformAdmin`) opens an intake for a client, providing a non-empty `presenting_needs` array drawn from the category vocabulary (`FOOD`, `HOUSING`, `HEALTHCARE`, `MENTAL_HEALTH`, `EMPLOYMENT`, `TRANSPORT`, `LEGAL_AID`, `CHILDCARE`), an `urgency` classification of `ROUTINE`, `PRIORITY`, or `EMERGENCY`, a `household_size` of at least 1, and a boolean `disability_flag` capturing whether the client self-identifies as having a disability. A new intake enters the system with `status` set to `DRAFT`.

The intake then follows a small cyclic lifecycle. Screening moves the intake from `DRAFT` to `SCREENED`, requiring the intake to currently be `DRAFT` and its `client_id` to resolve to an existing client; if the intake is not in `DRAFT` the screening call is rejected with `ERR_INTAKE_NOT_DRAFT`. On a successful screening the intake's `status` is set to `SCREENED`, `version` increments by 1, and `updated_at` refreshes. From `SCREENED` two divergent paths exist. If the caseworker realises the intake needs to be edited, the caseworker can reopen it, moving `SCREENED` back to `DRAFT` — this reopen path is only legal when the intake is currently `SCREENED` (otherwise `ERR_INTAKE_NOT_SCREENED`) and when no referral tied to this intake is currently `ACCEPTED` or `SERVICE_IN_PROGRESS`; a successful reopen sets `status` to `DRAFT`, increments `version` by 1, and refreshes `updated_at`, letting the caseworker edit and then re-screen. The second path from `SCREENED` is `CLOSED`, which is terminal and is triggered by the system — not by any caseworker action — the moment every referral tied to this intake has reached a terminal referral state and at least one referral exists; that transition sets `status` to `CLOSED`, increments `version` by 1, and refreshes `updated_at`.

### 3.3. Consent Management: Grant, Revoke, and Time-Based Expiry

Before a caseworker can dispatch a referral to a provider, the client must have granted consent to that specific provider. A consent grant is opened by a `Client` (acting on themself) or a caseworker (on the client's behalf), naming the target `provider_id` and the `scope` of information authorised — one of `BASIC_CONTACT` (contact-only), `FULL_CASE_FILE` (full case notes), or `HEALTHCARE_HIPAA` (HIPAA-scoped health information). At creation the server records `granted_at` as the current logical clock, sets `expires_at` to exactly `granted_at` plus 90 days, and sets `status` to `GRANTED`.

Two divergent paths exit the `GRANTED` state, and the two paths carry different side effects. The first is client-initiated revocation. When a `Client` (or a `PlatformAdmin` acting on behalf of one) revokes a consent grant, the grant's `status` must currently be `GRANTED` — a grant already `REVOKED` or `EXPIRED` cannot be revoked again and is rejected with `ERR_CONSENT_ALREADY_TERMINAL`. On a successful revoke, the grant's `status` is set to `REVOKED`, its `version` increments by 1, its `updated_at` refreshes, and every referral that was created under this consent and whose `status` is currently `PROPOSED`, `ACCEPTED`, or `SERVICE_IN_PROGRESS` is cascaded through the same withdraw path that a client-initiated withdrawal takes — each cascaded referral transitions to `WITHDRAWN`, decrements the target program's `capacity_slots_taken` by 1, may recompute `intake_posture`, cancels any `SCHEDULED` transport plan on that referral, and may bubble the parent intake to `CLOSED` when this referral was the last non-terminal one.

The second path from `GRANTED` is system expiry: when the logical clock advances to a moment at or after a `GRANTED` grant's `expires_at`, the grant is automatically transitioned to `EXPIRED`. This system transition sets `status` to `EXPIRED`, increments `version` by 1, and refreshes `updated_at`; unlike revocation, it deliberately does not cascade to in-flight referrals — expired consent leaves already-accepted and in-progress referrals alone and is instead caught downstream at referral accept and start-service (see §3.5).

### 3.4. Referral Creation: Eligibility Scoring, Travel Burden, and Capacity Reservation

A referral is the central artifact linking a client's screened intake to a provider's program under a signed consent grant. A caseworker opens a referral against an intake by supplying `program_id`, `consent_grant_id`, and `transport_mode` (the mode the client intends to use, one of `PUBLIC_TRANSIT`, `CAR`, `WALKING`, `AGENCY_SHUTTLE`). The intake must currently be `SCREENED` (otherwise `ERR_INTAKE_NOT_SCREENED`), the body's `program_id` and `consent_grant_id` must resolve (otherwise `ERR_INVALID_REQUEST`), and the target program's `intake_posture` must not be `CLOSED` (otherwise `ERR_PROGRAM_CLOSED_TO_INTAKE`). Beyond those state guards, several coupled business rules must be satisfied, evaluated in the priority order set out in §2.10.

The consent grant must be shaped correctly for this pairing: its `provider_id` must equal the program's `provider_id`, its `client_id` must equal the intake's `client_id`, and its `status` must be `GRANTED`. A mismatch on any of those three sub-conditions yields `ERR_CONSENT_PROVIDER_MISMATCH`. Next, the program's `category` must be one of the categories in the intake's `presenting_needs`; if the client is not presenting for a need this program addresses, the referral is rejected with `ERR_PROGRAM_CATEGORY_MISMATCH`.

The referral's eligibility score is then computed and compared to a fixed acceptance threshold of 75.0. The score is a weighted composite of five component scores. First, the income score: the ratio of the client's `monthly_income_cents` to the maximum of `eligibility_income_max_cents` and 1 (to avoid division by zero) is bucketed — a ratio of at most 0.50 scores 100.0, a ratio strictly greater than 0.50 but at most 0.80 scores 75.0, a ratio strictly greater than 0.80 but at most 1.00 scores 50.0, and a ratio strictly greater than 1.00 scores 0.0. Second, the age score: the client's age in whole years — computed as the floor of the elapsed years between the client's `date_of_birth` and the current logical clock date — scores 100.0 if it falls in the inclusive range from `eligibility_age_min` to `eligibility_age_max` and 0.0 otherwise. Third, the category score: 100.0 when the program's `category` is a member of the intake's `presenting_needs`, else 0.0. Fourth, the language match: 100.0 when the client's `preferred_language` is one of the provider's `languages_supported`, else 50.0. Fifth, the accessibility match: 100.0 when every value in the client's `accessibility_needs` is also present in the provider's `accessibility_features` (that is, the client's needs are a subset of the provider's features), else 0.0. The five component scores are combined by weighted sum with the fixed weights 0.30 for income, 0.20 for age, 0.25 for category, 0.15 for language, and 0.10 for accessibility. The resulting weighted sum is then multiplied by an urgency multiplier drawn from the intake's `urgency` — 1.00 for `ROUTINE`, 1.20 for `PRIORITY`, 1.50 for `EMERGENCY` — and rounded half-up to 2 decimal places to produce the final score. That final value is what is written to the referral's `eligibility_score` field, and if it is strictly less than 75.0 the referral is rejected with `ERR_ELIGIBILITY_BELOW_THRESHOLD`; a score of exactly 75.00 passes.

Two further per-referral checks apply. The client's age in whole years — again the floor of the elapsed years between `date_of_birth` and the current logical clock date — must fall within the program's inclusive age band; a value strictly below `eligibility_age_min` or strictly above `eligibility_age_max` yields `ERR_AGE_INELIGIBLE`. And the client's `monthly_income_cents` must be at most the program's `eligibility_income_max_cents`; equality passes and any strictly greater value yields `ERR_INCOME_INELIGIBLE`. Finally, the program must have room: the program's `capacity_slots_taken` must be strictly less than its `capacity_slots_total`. If the two values are equal, the program is full and the referral is rejected with `ERR_CAPACITY_EXHAUSTED`.

At referral creation the server also computes two independent travel-burden estimates and writes them to `travel_burden_naive_min` and `travel_burden_routed_min`. Both start from the same distance quantity: the sum of the absolute value of the difference between the client's `home_lat` and the provider's `location_lat` and the absolute value of the difference between the client's `home_lng` and the provider's `location_lng`, expressed in degrees. The naive-straight-line variant converts that degree distance to kilometres by multiplying by 111.0, divides by the speed in kilometres per hour associated with the referral's `transport_mode` (25.0 for `PUBLIC_TRANSIT`, 40.0 for `CAR`, 5.0 for `WALKING`, 20.0 for `AGENCY_SHUTTLE`), multiplies by 60.0 to convert to minutes, and rounds half-up to 2 decimal places; the result is written to `travel_burden_naive_min`. The routed variant applies the same steps but multiplies the kilometre distance by an additional winding factor of 1.35 before dividing by speed, so the routed value is always strictly greater than the naive value for the same inputs; the routed value is rounded half-up to 2 decimal places and written to `travel_burden_routed_min`. All intermediate arithmetic in this travel-burden pipeline — the two absolute-difference subtractions on the coordinates, their sum, the multiplication by 111.0, the routed variant's additional multiplication by 1.35, the division by mode speed, and the multiplication by 60.0 — is carried out on the exact decimal-literal representations of the coordinate and constant inputs (as if each were materialised via `Decimal(str(x))`) rather than in IEEE 754 binary floating-point, so a coordinate difference such as `|40.10 − 40.00| + |−74.05 − (−74.00)|` yields exactly `0.15` and the half-up-to-2 rounding therefore agrees with a decimal-literal reader of the same inputs. Both figures live on the referral in the same response.

The referral is also stamped with a provisional cost: `provisional_cost_cents` is set to the program's `unit_cost_cents` at the moment of creation, as a baseline estimate before any hours of service have been delivered. The referral itself is written with `status` set to `PROPOSED`. As a side effect of creation, the program's `capacity_slots_taken` is incremented by 1, and if that increment causes utilisation to cross a posture threshold upward the program's `intake_posture` recomputes accordingly and `version` is incremented by 1: utilisation is defined as `capacity_slots_taken` divided by `capacity_slots_total`, and the posture is `CLOSED` when this ratio is at least 1.00, `RESTRICTED` when it is at least 0.80 but strictly less than 1.00, and `OPEN` otherwise. Because the boundary comparisons use exact-integer counts, `capacity_slots_taken` times 100 being at least 80 times `capacity_slots_total` is the exact condition for the `OPEN → RESTRICTED` step, and `capacity_slots_taken` being at least `capacity_slots_total` is the exact condition for the `RESTRICTED → CLOSED` step.

### 3.5. Referral Lifecycle: Accept, Start Service, Complete, Decline, Withdraw

A referral enters `PROPOSED` and from there follows one of several paths.

**Provider acceptance.** Provider staff (or a `PlatformAdmin`) accepts a proposed referral, moving it from `PROPOSED` to `ACCEPTED`. Acceptance requires the referral to currently be `PROPOSED` (otherwise `ERR_REFERRAL_INVALID_STATE`), the linked consent grant's `status` to be `GRANTED` — not `REVOKED` and not `EXPIRED` — (otherwise `ERR_CONSENT_NOT_GRANTED`), and the program's `intake_posture` to not be `CLOSED` (otherwise `ERR_PROGRAM_CLOSED_TO_INTAKE`). A successful accept sets `status` to `ACCEPTED`, increments the referral's `version` by 1, and refreshes `updated_at`; the program's `capacity_slots_taken` is unchanged.

**Provider decline.** Alternatively the provider may decline the referral. Decline is only legal from `PROPOSED` (otherwise `ERR_REFERRAL_INVALID_STATE`); it sets the referral's `status` to `DECLINED`, increments its `version` by 1, refreshes `updated_at`, and — because the referral is exiting the in-flight status set — decrements the program's `capacity_slots_taken` by 1. That decrement may recompute the program's `intake_posture` downward: `CLOSED → RESTRICTED` when utilisation drops strictly below 1.00 while still being at least 0.80, and `RESTRICTED → OPEN` when utilisation drops strictly below 0.80. Any such posture change increments the program's `version` by 1. If this decline leaves every referral on the parent intake terminal and at least one referral exists on the intake, the intake auto-bubbles `SCREENED → CLOSED`, incrementing its `version` by 1.

**Start of service.** From `ACCEPTED`, provider staff advances the referral to `SERVICE_IN_PROGRESS`. This requires the referral to currently be `ACCEPTED` (otherwise `ERR_REFERRAL_INVALID_STATE`) and the linked consent grant to currently be `GRANTED` (otherwise `ERR_CONSENT_NOT_GRANTED`); a consent that has expired between accept and start-service will block start-service even though the accept succeeded. A successful start sets `status` to `SERVICE_IN_PROGRESS`, increments `version` by 1, and refreshes `updated_at`.

**Completion.** From `SERVICE_IN_PROGRESS`, provider staff files completion by supplying an `outcome_class` of either `SUCCESS` or `UNSUCCESSFUL`. Completion requires the referral to currently be `SERVICE_IN_PROGRESS` (otherwise `ERR_REFERRAL_INVALID_STATE`). A `SUCCESS` completion sets `status` to `COMPLETED_SUCCESS`; an `UNSUCCESSFUL` completion sets `status` to `COMPLETED_UNSUCCESSFUL`. Either way, the referral's `version` increments by 1, the program's `capacity_slots_taken` decrements by 1 with the same posture-recomputation cascade as decline, and if every referral on the parent intake is now terminal the intake auto-bubbles `SCREENED → CLOSED`.

**Client withdrawal.** A client (or a caseworker or `PlatformAdmin` acting on the client's behalf) can withdraw a referral from any non-terminal state — `PROPOSED`, `ACCEPTED`, or `SERVICE_IN_PROGRESS`. A withdrawal from a terminal state is rejected with `ERR_REFERRAL_INVALID_STATE`. Withdrawal sets `status` to `WITHDRAWN`, increments `version` by 1, and refreshes `updated_at`. It decrements the program's `capacity_slots_taken` by 1, may recompute `intake_posture` under the same threshold rules as decline, and may bubble the intake to `CLOSED`. In addition, withdrawal from either `ACCEPTED` or `SERVICE_IN_PROGRESS` cancels any `SCHEDULED` transport plan on this referral — the transport plan's `status` is set to `CANCELLED`, its `version` increments by 1, and its `updated_at` refreshes. Withdrawal from `PROPOSED` does not touch transport plans (none can yet exist at that stage in a normal caseflow).

The set of terminal referral states — `DECLINED`, `COMPLETED_SUCCESS`, `COMPLETED_UNSUCCESSFUL`, `WITHDRAWN` — is exactly what the intake-close bubble-up checks against when deciding whether every referral on an intake has finished.

### 3.6. Transport Coordination and the Per-Client 30-Minute Buffer

A caseworker (or `PlatformAdmin`) schedules a transport plan for a referral, supplying `pickup_start_ts`, `pickup_end_ts`, a `mode` of either `AGENCY_SHUTTLE` or `RIDESHARE_VOUCHER`, and a non-negative integer `cost_cents` recorded for provider reconciliation but never billed to the funder. The transport plan carries a `referral_id` linking it back to its parent referral. `pickup_end_ts` must be strictly greater than `pickup_start_ts`, and the plan enters the system with `status` set to `SCHEDULED`.

Transport plans use closed-closed pickup intervals — both `pickup_start_ts` and `pickup_end_ts` are inclusive — and are checked for conflict against every other `SCHEDULED` transport plan whose referral belongs to the same client (that is, whose referral's intake has the same `client_id` as this referral's intake's `client_id`). Two plans conflict when their true temporal separation — measured in seconds between the closing endpoint of the earlier interval and the opening endpoint of the later interval, and treated as exactly `0` whenever the two closed-closed intervals overlap (regardless of the magnitude of the overlap) — is strictly less than 30 minutes. Equivalently, letting `gap_a = new.start − other.end` and `gap_b = other.start − new.end` in seconds, the separation is `max(gap_a, gap_b, 0)`, and a conflict is raised when that separation is strictly less than 1800 seconds. A conflict is rejected with `ERR_TRANSPORT_OVERLAP`; a separation of exactly 30 minutes is permitted.

A transport plan reaches `CANCELLED` only through a cascade — never through a direct client or staff action — when the parent referral transitions to `WITHDRAWN` from either `ACCEPTED` or `SERVICE_IN_PROGRESS`. That cascade sets the transport plan's `status` to `CANCELLED`, increments its `version` by 1, and refreshes its `updated_at`.

### 3.7. Outcomes, the Funder Grant Ledger, and Compensating Reversal

Once a referral has completed, a caseworker or provider staff (or `PlatformAdmin`) files an outcome report against it, supplying the classification `outcome` (one of `FULLY_MET`, `PARTIALLY_MET`, `UNMET`), the number of `service_hours` actually delivered (a non-negative number), and a boolean `follow_up_needed` recording whether caseworker follow-up is scheduled. The server computes the final service cost — the final variant of the service-cost estimate, distinct from the provisional variant that was set at referral creation — using the outcome class and the delivered hours. If the outcome is `UNMET` the raw ratio is exactly 0.50; if the outcome is `PARTIALLY_MET` or `FULLY_MET` the raw ratio is 0.50 plus the delivered `service_hours` multiplied by 0.10, and no upper cap is applied. The raw ratio is then multiplied by the program's `unit_cost_cents`, and the resulting floating-point cents value is rounded half-up in a single step to whole cents to produce `service_cost_final_cents`. Because the provisional cost was simply `unit_cost_cents`, the final can be strictly less than, equal to, or strictly greater than the provisional; the caseworker sees both figures on the referral and outcome respectively.

Filing an outcome debits the funder's `grant_cents_remaining` by exactly `service_cost_final_cents`. Before the debit is applied, the server checks that the funder has room: if the newly computed `service_cost_final_cents` is strictly greater than `grant_cents_remaining` the file is rejected with `ERR_GRANT_INSUFFICIENT` (HTTP 402), and equality passes. On success the outcome enters the system with `status` set to `ACTIVE`, the debit is applied, and `grant_cents_remaining` is recomputed as `grant_cents_total` minus the sum of `service_cost_final_cents` across every outcome for this funder whose `status` is `ACTIVE`.

Reversing an outcome is a `PlatformAdmin`-only compensating action. The outcome must currently be `ACTIVE`; if it is already `REVERSED` — or if it is `ACTIVE` but its referral's program has advanced to `funder_reporting_posture` `ARCHIVED`, in which case the program's outcomes are frozen — the reverse is rejected with `ERR_OUTCOME_ALREADY_REVERSED`. On success the outcome's `status` is set to `REVERSED`, its `version` increments by 1, its `updated_at` refreshes, and the funder's `grant_cents_remaining` is credited by exactly the same `service_cost_final_cents` that was debited at outcome creation, so a (create, reverse) pair on the same outcome returns `grant_cents_remaining` to the exact integer-cents value it held before the create.

### 3.8. Funder Reporting, Rounding Variants, and Fiscal-Year Rollover

Periodically a `PlatformAdmin` generates a report for a funder covering a bounded reporting window. The report body supplies `reporting_period_start` (inclusive lower bound), `reporting_period_end` (exclusive upper bound, strictly greater than the start — otherwise `ERR_REPORTING_PERIOD_INVALID`), and a `rounding_variant` selecting between `PER_REFERRAL_ROUND_THEN_SUM` and `SUM_THEN_ROUND`. The set of outcomes included is every outcome report whose `status` is `ACTIVE`, whose referral's program is underwritten by this funder, and whose `created_at` falls in the half-open window from `reporting_period_start` (inclusive) up to but not including `reporting_period_end` — outcomes ordered by `created_at` ascending as the tie-breaker.

For each such outcome the server derives a raw (unrounded, floating-point) cost using the same expression as the final service-cost calculation: when the outcome is `UNMET` the raw is the program's `unit_cost_cents` times 0.50, and when the outcome is `PARTIALLY_MET` or `FULLY_MET` the raw is the program's `unit_cost_cents` multiplied by the quantity 0.50 plus the outcome's `service_hours` times 0.10. The two rounding variants then combine these per-outcome raws differently. Under `PER_REFERRAL_ROUND_THEN_SUM` the server sums the already-rounded per-outcome `service_cost_final_cents` values as they were stored on each outcome; each per-outcome rounding may introduce up to a 0.5-cent error that accumulates across the input set. Under `SUM_THEN_ROUND` the server first sums the raw floating-point values across every outcome in the set, then applies round-half-up once at the end to produce whole cents. The two totals can and often will differ for the same input set — the difference between them can be as large as approximately half a cent per outcome contributing a fractional raw — which is why the caller must attest to a specific rounding variant on each report. The chosen result is written to the report's `total_disbursement_cents`.

The report also records `total_referrals` (the count of referrals whose program's `funder_id` matches this funder and whose `created_at` falls in the same half-open window), `total_completions` (the count of those referrals whose `status` is `COMPLETED_SUCCESS` or `COMPLETED_UNSUCCESSFUL`), and `language_breakdown` (a map from each supported language enum value — `EN`, `ES`, `FR`, `ZH`, `VI`, `AR` — to the count of referrals in the window whose client's `preferred_language` equals that language).

Generating the report has two side effects on the underlying programs. Every program that contributed at least one outcome to the report advances its `funder_reporting_posture` from `OPEN` to `LOCKED` and increments its `version` by 1. Later, when the logical clock crosses the funder's fiscal-year boundary — the first moment when the clock's month equals the funder's `fiscal_year_start_month` and the day is 1 — every program still `LOCKED` under this funder advances from `LOCKED` to `ARCHIVED` and increments its `version` by 1. Locked programs may still receive new outcome reports (subject to grant availability) and existing outcomes may still be reversed; archived programs may not have any of their existing outcomes reversed. Note that `FunderReport` is a computed aggregate and, as noted in §2.4, carries only `id` and `created_at`; it has neither an `updated_at` nor a `version`.

## 4. Endpoint Definitions

New resource creations return HTTP 201; state transitions, patches, list endpoints, and the administrative clock-set capability return HTTP 200. All 4xx error responses follow the envelope in §2.2. The table below is a minimal index; the request body, response body, and side effects of each endpoint are reconstructed from the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Advance the logical clock to `to_iso8601`; triggers consent expiry and program fiscal-year archival cascades. | `PlatformAdmin` |
| POST | `/funders` | Register a new funder; initialises `grant_cents_remaining` equal to `grant_cents_total`. | `PlatformAdmin` |
| GET | `/funders/{id}` | Fetch a single funder. | `PlatformAdmin`, `FunderReporter` |
| GET | `/funders/{id}/reports` | List funder reports for the funder. | `PlatformAdmin`, `FunderReporter` |
| POST | `/funders/{id}/reports` | Generate a new funder report over `[reporting_period_start, reporting_period_end)`. | `PlatformAdmin` |
| POST | `/providers` | Register a new provider. | `PlatformAdmin` |
| GET | `/providers/{id}` | Fetch a single provider. | `PlatformAdmin`, `ProviderStaff`, `Caseworker` |
| GET | `/providers/{id}/programs` | List programs operated by the provider. | `PlatformAdmin`, `ProviderStaff`, `Caseworker` |
| POST | `/programs` | Create a new program under an existing provider and funder. | `PlatformAdmin` |
| GET | `/programs/{id}` | Fetch a single program. | `PlatformAdmin`, `ProviderStaff`, `Caseworker`, `Client` |
| GET | `/programs` | List programs with optional `provider_id`, `funder_id`, and `category` filters. | `PlatformAdmin`, `Caseworker` |
| PATCH | `/programs/{id}` | Update program fields; guarded by `expected_program_version` OCC. | `PlatformAdmin` |
| POST | `/programs/{id}/availability-windows` | Add an availability window to a program. | `ProviderStaff`, `PlatformAdmin` |
| GET | `/programs/{id}/availability-windows` | List availability windows for a program. | `ProviderStaff`, `PlatformAdmin`, `Caseworker` |
| POST | `/clients` | Register a new client. | `Caseworker`, `PlatformAdmin` |
| GET | `/clients/{id}` | Fetch a single client; a `Client` may only fetch themselves. | `Client`, `Caseworker`, `PlatformAdmin` |
| POST | `/clients/{id}/intakes` | Create a new intake for the client with `status` `DRAFT`. | `Caseworker`, `PlatformAdmin` |
| GET | `/intakes/{id}` | Fetch a single intake. | `Caseworker`, `PlatformAdmin` |
| GET | `/intakes` | List intakes with optional `client_id` and `status` filters. | `Caseworker`, `PlatformAdmin` |
| POST | `/intakes/{id}/screen` | Screen the intake: `DRAFT` → `SCREENED`. | `Caseworker`, `PlatformAdmin` |
| POST | `/intakes/{id}/reopen` | Reopen a screened intake: `SCREENED` → `DRAFT`. | `Caseworker`, `PlatformAdmin` |
| POST | `/clients/{id}/consent-grants` | Client (or caseworker on client's behalf) grants consent to a provider. | `Client`, `Caseworker`, `PlatformAdmin` |
| GET | `/consent-grants/{id}` | Fetch a single consent grant. | `Client`, `Caseworker`, `ProviderStaff`, `PlatformAdmin` |
| GET | `/consent-grants` | List consent grants with optional `client_id`, `provider_id`, and `status` filters. | `Client`, `Caseworker`, `ProviderStaff`, `PlatformAdmin` |
| POST | `/consent-grants/{id}/revoke` | Revoke a consent grant; cascades in-flight referrals to `WITHDRAWN`. | `Client`, `PlatformAdmin` |
| POST | `/intakes/{id}/referrals` | Create a referral from an intake to a program under a consent grant. | `Caseworker`, `PlatformAdmin` |
| GET | `/referrals/{id}` | Fetch a single referral. | `Caseworker`, `ProviderStaff`, `PlatformAdmin` |
| GET | `/referrals` | List referrals with optional `intake_id`, `program_id`, `consent_grant_id`, and `status` filters. | `Caseworker`, `ProviderStaff`, `PlatformAdmin` |
| POST | `/referrals/{id}/accept` | Provider accepts: `PROPOSED` → `ACCEPTED`. | `ProviderStaff`, `PlatformAdmin` |
| POST | `/referrals/{id}/decline` | Provider declines: `PROPOSED` → `DECLINED`. | `ProviderStaff`, `PlatformAdmin` |
| POST | `/referrals/{id}/start-service` | Provider starts service: `ACCEPTED` → `SERVICE_IN_PROGRESS`. | `ProviderStaff`, `PlatformAdmin` |
| POST | `/referrals/{id}/complete` | Provider completes service; `outcome_class` decides which terminal state. | `ProviderStaff`, `PlatformAdmin` |
| POST | `/referrals/{id}/withdraw` | Client (or delegate) withdraws the referral from any non-terminal state. | `Client`, `Caseworker`, `PlatformAdmin` |
| POST | `/referrals/{id}/transport-plans` | Create a transport plan for the referral. | `Caseworker`, `PlatformAdmin` |
| GET | `/referrals/{id}/transport-plans` | List transport plans for the referral. | `Caseworker`, `ProviderStaff`, `PlatformAdmin` |
| POST | `/referrals/{id}/outcome-reports` | File an outcome report against a completed referral; debits the funder grant. | `Caseworker`, `ProviderStaff`, `PlatformAdmin` |
| GET | `/referrals/{id}/outcome-reports` | List outcome reports for the referral. | `Caseworker`, `ProviderStaff`, `PlatformAdmin`, `FunderReporter` |
| POST | `/outcome-reports/{id}/reverse` | Reverse an outcome report as a compensating action; credits the funder grant. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FUNDER_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_INTAKE_NOT_FOUND` | 404 |
| `ERR_CONSENT_GRANT_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_OUTCOME_REPORT_NOT_FOUND` | 404 |
| `ERR_INTAKE_NOT_DRAFT` | 409 |
| `ERR_INTAKE_NOT_SCREENED` | 409 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_CONSENT_ALREADY_TERMINAL` | 409 |
| `ERR_OUTCOME_ALREADY_REVERSED` | 409 |
| `ERR_PROGRAM_CLOSED_TO_INTAKE` | 409 |
| `ERR_CONSENT_NOT_GRANTED` | 422 |
| `ERR_CONSENT_PROVIDER_MISMATCH` | 422 |
| `ERR_PROGRAM_CATEGORY_MISMATCH` | 422 |
| `ERR_ELIGIBILITY_BELOW_THRESHOLD` | 422 |
| `ERR_AGE_INELIGIBLE` | 422 |
| `ERR_INCOME_INELIGIBLE` | 422 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_WINDOW_SLOTS_EXCEED_CAPACITY` | 422 |
| `ERR_TRANSPORT_OVERLAP` | 409 |
| `ERR_CAPACITY_EXHAUSTED` | 422 |
| `ERR_GRANT_INSUFFICIENT` | 402 |
| `ERR_REPORTING_PERIOD_INVALID` | 422 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
