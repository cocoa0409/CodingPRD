# Holiday Toy Drive API — Product Requirements Document

## 1. Introduction

Every holiday season, community toy drives confront the same operational knot: partner agencies refer hundreds of families in overlapping ways, donors pledge gifts against wish lists that shift as caseworkers verify eligibility, and a single missed gift-return deadline can leave a child empty-handed on distribution day. This document describes the **Holiday Toy Drive** API, a seasonal campaign platform modeled on the classic Angel Tree program. It tracks the full lifecycle from campaign setup, partner-agency family referral with automated duplicate detection, child registration and wish-list capture, donor adoption with a 72-hour confirmation window, gift intake and sorting, backfill purchasing from a central pool when donors fall through, distribution-day slot scheduling and pickup, and post-season donor thank-you outreach.

The API is mounted under `/toy-drive`. It serves five distinct operator roles — program administrators, partner-agency coordinators, caseworkers, donors, and distribution volunteers — each with segregated responsibilities. A donor's pledge is not a commitment until the donor confirms within seventy-two hours; a family is not eligible for adoption until a caseworker who did not begin the review also verifies it; and no gift is ever recorded as received past the campaign's gift-return deadline unless the platform has been configured with an explicit grace window and the volunteer supplies an override note. The system is deliberately pessimistic about concurrency: any state-changing operation whose cascade could be invalidated by a parallel write carries an optimistic-concurrency field, and any family whose attributes shift between the donor's browse and the donor's pledge is rejected with a stale-version signal so the donor re-reads before committing.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, a non-empty identifier for the acting principal, and `X-User-Role`, one of the five declared role names. Missing or malformed headers yield `ERR_UNAUTHENTICATED` (HTTP 401). A role that is well-formed but not permitted for the target endpoint yields `ERR_FORBIDDEN` (HTTP 403).

The five roles, spelled exactly as the server recognizes them, are `PlatformAdmin`, `AgencyCoordinator`, `CaseWorker`, `Donor`, and `DistributionVolunteer`.

Two of the roles are entity-backed, and three are opaque. When `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the acting `PartnerAgency` row; ownership checks on any resource that references a `PartnerAgency` (a family referral, a child, a wish item submitted under that agency's families) compare the resource's agency foreign key to `X-User-ID`. When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor` row; ownership checks on adoptions, gifts, and donor self-reads compare the donor foreign key to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `CaseWorker`, or `DistributionVolunteer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_id` on `FamilyAuditEvent`) but does not compare it against any entity's `id`.

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

All list endpoints accept optional `limit` and `offset` query parameters. The default `limit` is 10, the minimum permitted `limit` is 1, and the maximum permitted `limit` is 100. The default `offset` is 0. List responses are always sorted by `created_at` ascending (oldest first), and the response `meta` block carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Identifiers, and Timestamps

Every persisted resource carries an `id` field — a server-minted UUID with no type prefix — and a `created_at` field, an ISO 8601 UTC timestamp with three fractional digits. All entities except `FamilyAuditEvent` also carry `updated_at` (ISO 8601 UTC with three fractional digits, refreshed on every mutation) and `version` (an integer optimistic-concurrency counter that starts at 1 and increments on every mutation). `FamilyAuditEvent` is the single exception: it is append-only, carries only `id` and `created_at`, and has neither `updated_at` nor `version`. Audit events are written by the server and are never directly mutated by any role; their `occurred_at` field records the server-stamped UTC instant of the event.

### 2.5. Logical Clock, Calendar Windows, and the Test-Driving Capability

All deadline, grace-window, and slot-window rules in this document read from the server's **logical clock**, not from wall-clock time. On server startup the logical clock is exactly `2026-08-01T00:00:00Z`; it never falls back to real time. A `PlatformAdmin` may drive the logical clock forward (or set it to any arbitrary ISO 8601 UTC instant) by way of a test-driving capability that accepts a `to_iso8601` payload and returns the resulting `current_utc` value. Time-based transitions — most notably adoption pledge expiry and slot no-show — are evaluated lazily, on the next read or write that depends on them, after the clock moves.

Four calendar windows anchor every campaign. The `intake_open_at` and `intake_close_at` instants bound when partner agencies may submit new family referrals. The `gift_return_deadline` instant is the moment after which unfulfilled adoptions are auto-cancelled and their children become backfill-eligible. The `distribution_date` instant is the calendar day on which distribution events occur and is also the reference date against which each child's age band is computed.

### 2.6. Monetary Units, Precision, and Rounding

All monetary amounts are integer cents (so a $75.00 gift cap is 7500). Where a score or rate involves a fractional step — the backfill child-selector score is the only such calculation — the final score is rounded half-up to two decimal places. The child's age, by contrast, is computed in whole years floored from a day count, never rounded.

### 2.7. Optimistic Concurrency Control

Four write operations require the caller to declare the version it last observed of a parent entity, so a stale view never silently overwrites another writer's cascade. The required field names are not optional:

- A pledge to create an `Adoption` must carry `expected_family_version` matching the target `Family` row's current `version`. If a duplicate-flag resolution or a sibling adoption confirm has advanced the family's version since the donor last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A booking that creates a `DistributionSlot` must carry `expected_event_version` matching the parent `DistributionEvent`'s current `version`. If another volunteer has just booked the final open slot and bumped the event's version, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A request to advance a `Campaign` between phases must carry `expected_campaign_version` matching the campaign's current `version`. Back-to-back advance calls must each observe the freshest version because the prior advance's cascades (adoption expiry, child backfill-eligibility flips) silently bump the campaign's version; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- An update to the `SeasonSettings` singleton must carry `expected_settings_version` matching the singleton's current `version`, so two admins cannot each believe their own update was the one that landed; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. The mutation that succeeds increments the parent's `version`, refreshes `updated_at`, and proceeds.

### 2.8. Nested Path Resolution and Referential Existence

Any URL that templates one or more resource identifiers resolves them left-to-right, returning `ERR_NOT_FOUND` (HTTP 404) on the first identifier that does not resolve to an existing row. The same `ERR_NOT_FOUND` applies to every `*_id` foreign key supplied in a request body — for example `family_id`, `child_ids`, or `wish_item_id` — when the referenced row does not exist. A required field that is missing, of the wrong type, or an enum value outside its declared set yields `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Privacy of Family Information

Donor-facing reads never return caregiver PII. Specifically, the fields `primary_caregiver_name`, `caregiver_dob`, `address_text`, and `phone_last4` are stripped from any response served under a donor role, and any donor-scoped request that attempts to filter on or read those fields is rejected with `ERR_PRIVACY_VIOLATION` (HTTP 403). What a donor sees for a child depends on the campaign's `privacy_mode`: under `STRICT` (the default), the donor-facing view shows only the child's `first_name` and `age_band`; under `STANDARD`, the donor additionally sees the child's `interest_tags` and `clothing_size`. Every donor read of a family — list or single fetch — also writes a `FamilyAuditEvent` with `event_type` equal to `PII_VIEW` on the family in question, recording `actor_role` and `actor_id` of the donor.

### 2.10. Audit Trail on Family-Scoped Events

The `FamilyAuditEvent` entity records family-scoped actions. The `event_type` field is one of `PII_VIEW`, `PII_EXPORT`, `STATUS_CHANGE`, `DUPLICATE_FLAGGED`, `DUPLICATE_RESOLVED`, or `CONSENT_CHANGE`. Each row captures the `family_id` it concerns, the `actor_role` and `actor_id` of the actor who caused it, a free-form `payload_json` for before/after values and reason codes, and the server-stamped `occurred_at` instant. Audit events are listed via the family's reverse-reachability endpoint and are readable only by `PlatformAdmin` and `CaseWorker`.

### 2.11. The SeasonSettings Singleton

Exactly one `SeasonSettings` row exists for the deployment, keyed by `singleton_key` which must equal the literal string `GLOBAL`. The singleton carries four program-wide knobs. `duplicate_auto_detect_enabled` (default `true`) controls whether family-create auto-computes the duplicate hash and raises `DuplicateFlag` rows on hash collisions. `duplicate_hash_salt` is an installation-wide string mixed into the hash so hashes are not portable across deployments. `late_donor_grace_hours` (default 0, permitted range 0 through 72) is the number of hours past the campaign's `gift_return_deadline` during which a gift may still be marked received provided the volunteer supplies a non-empty `override_note`. `major_donor_threshold_cents` (default 50000) is the `giving_history_cents` floor at or above which a donor is classified as a major donor for thank-you template selection. The singleton is auto-created with defaults on the first read, and updating it carries the OCC rule described in §2.7.

## 3. Business Logic & Workflows

### 3.1. Campaign Setup and the Seasonal Lifecycle

A `PlatformAdmin` opens a season by creating a `Campaign`. The create payload carries `season_year` (a four-digit year, at least 2020 and at most 2100, unique across all campaigns), `intake_open_at`, `intake_close_at`, `gift_return_deadline`, `distribution_date`, `max_children_per_family` (at least 1 and at most 12), `max_gift_value_cents` (at least 1000 and at most 100000), `min_gift_value_cents` (at least 0 and strictly less than `max_gift_value_cents`), `backfill_budget_cents` (at least 0), and an optional `privacy_mode` that defaults to `STRICT` and may be either `STRICT` or `STANDARD`. The campaign begins in `DRAFT`, with `backfill_spent_cents` at 0 and `version` at 1.

A campaign moves through seven lifecycle states — `DRAFT`, `INTAKE_OPEN`, `MATCHING`, `DISTRIBUTION_PREP`, `DISTRIBUTION`, `RECONCILIATION`, `CLOSED` — and `CLOSED` is terminal. While a campaign is in `DRAFT`, the `PlatformAdmin` may patch any of its input fields. Once intake is open, only `distribution_date` may shift, and shifting it carries a side effect: every child registered under the campaign has its `age_band` recomputed lazily against the new distribution date, and any child whose band would change keeps the old band but has a `FamilyAuditEvent` written recording the change.

Opening intake — transitioning `DRAFT → INTAKE_OPEN` — requires that the current logical instant lie within the declared intake window: `intake_open_at` must be at or before the current instant, and the current instant must be at or before `intake_close_at`. A successful open stamps `updated_at` and increments the campaign's `version`. Closing intake — transitioning `INTAKE_OPEN → MATCHING` — requires that the current instant be at or after `intake_close_at`, and it carries a hard cascade: every `Family` still in `REFERRED` or `UNDER_REVIEW` under this campaign is transitioned to `REJECTED` with reason `INTAKE_CLOSED_INCOMPLETE`, and every child of those families in `REGISTERED` transitions to `CLOSED` (`REGISTERED → CLOSED`). The campaign's `version` increments.

From `MATCHING`, advancing the campaign moves it to `DISTRIBUTION_PREP`. This advance is gated on the current instant being at or after the campaign's `gift_return_deadline`, and it triggers the unfulfilled-adoption expiry sweep: every `Adoption` still in `PLEDGED` or `CONFIRMED` whose snapshotted `return_deadline` lies before the current instant is moved to `EXPIRED`, and every child covered by such an expired adoption who is still in `ADOPTED` is flipped to `BACKFILL_ELIGIBLE`. The campaign version increments. Advancing again moves `DISTRIBUTION_PREP → DISTRIBUTION`, which requires that at least one `DistributionEvent` under the campaign has reached `OPEN_FOR_SLOTS` or any later state. A further advance moves `DISTRIBUTION → RECONCILIATION` once every `DistributionEvent` under the campaign is in `COMPLETED` or `CANCELLED`; this advance sweeps every family still in `MATCHED`, `PARTIALLY_FULFILLED`, `FULFILLED`, or `BACKFILLED` to `CLOSED`. Finally, a `PlatformAdmin` closes the campaign — `RECONCILIATION → CLOSED` — only when no `Adoption` remains in `PLEDGED`, `CONFIRMED`, or `PARTIALLY_RECEIVED` under the campaign, and no `DuplicateFlag` remains `OPEN` on any of the campaign's families. Close stamps `updated_at` and increments `version`.

The advance endpoint is one of the four OCC-guarded writes listed in §2.7: each advance call must present `expected_campaign_version` equal to the campaign's current `version`, because the prior advance's cascades silently bumped the version. A stale `expected_campaign_version` yields `ERR_STALE_VERSION` (HTTP 412).

### 3.2. Partner Agency Onboarding and Quota

`PlatformAdmin` registers partner agencies with an `agency_code` (3 to 16 uppercase alphanumeric characters, unique, printed on referral forms), `legal_name`, `referral_quota` (at least 1 and at most 500), and `contact_email`. An agency begins in `ACTIVE`. Suspending an agency moves it to `SUSPENDED` and increments its `version`; a `SUSPENDED` agency may not submit new referrals, and any attempt to do so is rejected with `ERR_AGENCY_SUSPENDED` (HTTP 409).

Each agency has a computed `referral_used_count`, the count of `Family` rows referred by this agency for the current campaign whose status is non-terminal — that is, not in `REJECTED`, `WITHDRAWN`, or `CLOSED`. Submitting a referral when `referral_used_count` has reached `referral_quota` is rejected with `ERR_AGENCY_QUOTA_EXCEEDED` (HTTP 409).

### 3.3. Family Referral, Duplicate Detection, and the Review Loop

An `AgencyCoordinator` submits a family referral by posting under their own agency. The create payload carries `agency_id`, `campaign_id`, `primary_caregiver_name`, `caregiver_dob` (a date in `YYYY-MM-DD` form), `household_size` (at least 1 and at most 20), `address_text` (free-form street address), and `phone_last4` (exactly four digits). Validation of a family-create runs in the following order: authentication and role checks first, then URL and body referential existence, then state and OCC checks, then the temporal intake-window check (the current instant must be at or after `intake_open_at` and at or before `intake_close_at`, and the campaign must currently be in `INTAKE_OPEN` — a failure yields `ERR_INTAKE_CLOSED`, HTTP 409), then the uniqueness and quota checks, and finally the constraint checks specific to the request body.

On create, the server computes the family's `duplicate_hash`: it lowercases and trims the `caregiver_dob`, concatenates the result with a pipe separator, then the `phone_last4`, another pipe separator, and the digit characters of `address_text` with all non-digit characters stripped; the resulting string is prefixed with the `SeasonSettings.duplicate_hash_salt` followed by a colon, and the whole is hashed with SHA-256 rendered as a 64-character lowercase hexadecimal string. When `duplicate_auto_detect_enabled` is `true`, the server then scans the campaign for any other `Family` row in a non-terminal state (not `REJECTED`, not `WITHDRAWN`, not `CLOSED`) with the identical `duplicate_hash`, and for each match it creates a `DuplicateFlag` with `detected_by` equal to `AUTO_HASH`, `family_id` pointing at the new family, and `other_family_id` pointing at the matched family. Every family create also writes a `FamilyAuditEvent` of type `STATUS_CHANGE`.

A `CaseWorker` may additionally raise a duplicate flag manually between any two families by posting a payload carrying `family_id` and `other_family_id`; such a flag has `detected_by` equal to `MANUAL_REPORT` and writes a `FamilyAuditEvent` of type `DUPLICATE_FLAGGED`. Every flag carries a `status` field that begins at `OPEN` and an optional `resolution_note` that the reviewer records at resolution time.

Resolving a flag is the caseworker's call. Confirming it — `OPEN → CONFIRMED_DUPLICATE` — rejects the flagged family (if the family is not already in a terminal status) with reason `CONFIRMED_DUPLICATE`, points the flagged family's self-referential `duplicate_of_family_id` at the suspected primary record, and writes a `FamilyAuditEvent` of type `DUPLICATE_RESOLVED` on both families. Dismissing it — `OPEN → DISMISSED` — writes the `DUPLICATE_RESOLVED` audit event with no family-side cascade. Both resolution actions accept an optional `resolution_note`.

The family lifecycle begins at `REFERRED`. A `CaseWorker` begins review — `REFERRED → UNDER_REVIEW` — provided no `OPEN` `DuplicateFlag` references this family in either direction (neither as `family_id` nor as `other_family_id`); a violation yields `ERR_DUPLICATE_FLAG_OPEN` (HTTP 409). From `UNDER_REVIEW`, three paths are defined. The caseworker may verify the family — `UNDER_REVIEW → VERIFIED` — provided the family's `total_children_count` is at least 1, every child of the family has a computed `age_band`, and no `OPEN` duplicate flag references the family; verification stamps `verified_at`, cascades every child of the family from `REGISTERED` to `WISH_LOCKED`, and accepts an optional `verification_note`. The caseworker may reject the family — `UNDER_REVIEW → REJECTED` — which cascades every child of the family to `CLOSED` and every wish item of those children to `REJECTED`. Or the caseworker may return the family to referral — `UNDER_REVIEW → REFERRED` — a cyclic revision loop that may be exercised any number of times while the caseworker awaits further documentation. Reject, return-to-referral, and verify all accept an optional `verification_note`, and each writes a `FamilyAuditEvent` of type `STATUS_CHANGE`.

Two segregation-of-duties rules gate the verify action. The `CaseWorker` whose `actor_id` is recorded on the `STATUS_CHANGE` audit event that moved this family from `REFERRED` to `UNDER_REVIEW` must not also be the actor of the verify call; a violation yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The same rule, applied symmetrically, prevents the `PlatformAdmin` who created a `BackfillPurchase` from later marking that purchase purchased.

Once `VERIFIED`, a family may be withdrawn — `VERIFIED → WITHDRAWN` — provided no `Adoption` in `PLEDGED`, `CONFIRMED`, or `PARTIALLY_RECEIVED` references the family; withdrawal cascades every child to `CLOSED` and writes a `STATUS_CHANGE` audit event.

### 3.4. Child Registration, Age Bands, and Wish Lists

Children are registered under a family by an `AgencyCoordinator` or `CaseWorker`. The create payload carries `first_name`, `dob` (a `YYYY-MM-DD` date), `gender` (one of `F`, `M`, or `X`), `clothing_size` (free text such as "youth M" or "toddler 4T"), and `interest_tags` (a list of lowercase interest keywords such as `lego`, `soccer`, or `art`). Adding a child is capped by the campaign's `max_children_per_family`: if the family's `total_children_count` has already reached that cap, the create is rejected with `ERR_FAMILY_CHILD_CAP` (HTTP 409).

On create, the server computes the child's `age_band` from the child's `dob` and the parent campaign's `distribution_date`. The age in days is the whole-day floor of the difference between `distribution_date` and `dob`. The age in years is the floor of that day count divided by 365.25. The band is then `INFANT` if the age in years is less than 1, `TODDLER` if it is at least 1 and less than 3, `PRESCHOOL` if it is at least 3 and less than 5, `SCHOOL_AGE` if it is at least 5 and less than 10, `PRETEEN` if it is at least 10 and less than 13, and `TEEN` if it is at least 13 and less than 19. A child whose age in years is 19 or greater is rejected at create time with `ERR_CHILD_TOO_OLD` (HTTP 422). This band is computed eagerly at child create using the campaign's distribution date at the moment of the POST; if a `PlatformAdmin` later shifts `distribution_date`, the band is recomputed lazily per §3.1.

Each child carries a computed `gift_estimate_cents`, the sum of `estimated_price_cents` over the child's wish items whose status is either `REQUESTED` or `APPROVED`. Items in `REJECTED`, `COMMITTED`, `RECEIVED`, `DELIVERED`, or `BACKFILL_SOURCED` are excluded from the sum. The estimate is recomputed every time a wish item is approved, rejected, or removed.

Wish items are added to a child by an `AgencyCoordinator` or `CaseWorker`. The create payload carries `description`, `category` (one of `TOY`, `CLOTHING`, `BOOK`, `SPORTS`, `ELECTRONICS`, `ART`, `OTHER`), `estimated_price_cents` (at least 100 and at most the campaign's `max_gift_value_cents`), and `priority_rank` (an integer from 1 to 10, where 1 is the most-wanted; the rank must be unique across this child's wish items). Violating the per-child uniqueness of `priority_rank`, the campaign's `season_year` uniqueness, an agency's `agency_code` uniqueness, or a donor's `email` uniqueness all yield `ERR_DUPLICATE` (HTTP 409).

A wish item begins at `REQUESTED`. A `CaseWorker` approves it — `REQUESTED → APPROVED` — provided the parent child is in `REGISTERED` or `WISH_LOCKED` and the sum of the child's other `APPROVED` items plus this item's `estimated_price_cents` is at or below the campaign's `max_gift_value_cents`. The same per-child cap applies at wish-item create: the sum of the child's `REQUESTED` plus `APPROVED` items after the write must not exceed `max_gift_value_cents`. Either violation yields `ERR_WISH_VALUE_EXCEEDED` (HTTP 422). Approving or rejecting a wish item recomputes the child's `gift_estimate_cents`. A rejected item — `REQUESTED → REJECTED` — is terminal.

### 3.5. Donor Registration and the Adoption Pledge

`PlatformAdmin` registers donors with an `email` (RFC 5322, unique), a `display_name` used on thank-you letters, and three optional fields: `max_adoptions_per_season` (default 5, permitted range 1 through 50), `preferred_age_bands` (default empty list, a soft signal to the matching selector), and `thank_you_opt_in` (default `true`). A donor begins in `ACTIVE` and carries a computed `giving_history_cents`, the running total of `declared_value_cents` over all gifts in `RECEIVED` or `DELIVERED` attributed to this donor across all campaigns. Donors may fetch only their own record; the donors list endpoint is `PlatformAdmin`-only because it exposes PII.

A donor pledges an adoption by posting a payload carrying `campaign_id`, `donor_id`, `family_id`, `scope`, an optional `child_ids` list, and the OCC field `expected_family_version`. Two scopes are defined. Under `WHOLE_FAMILY`, the adoption commits to every child of the family currently in `WISH_LOCKED`; under `CHILD_LIST`, it commits only to the listed children, and `child_ids` is otherwise empty. Coverage is validated strictly: every id in `child_ids` must reference a child of the named family and be in `WISH_LOCKED`, and a `WHOLE_FAMILY` adoption requires the family to have at least one child in `WISH_LOCKED`. A coverage violation yields `ERR_ADOPTION_COVERAGE_INVALID` (HTTP 422).

At pledge time the server freezes a `commitment_cents` snapshot on the adoption: the sum of `gift_estimate_cents` over the covered children, captured at that instant and never recomputed even if a wish item is later edited. The adoption begins in `PLEDGED`, stamped with `pledged_at`. Pledging also enforces the donor's concurrent-adoption cap: the count of this donor's adoptions in this campaign that are in `PLEDGED`, `CONFIRMED`, or `PARTIALLY_RECEIVED` must be strictly less than `max_adoptions_per_season`; otherwise the pledge is rejected with `ERR_ADOPTION_CAP_EXCEEDED` (HTTP 409). A successful pledge increments the family's `version`, which is why the `expected_family_version` OCC check (§2.7) is the canonical guard against a donor pledging against a family whose state has shifted under them.

### 3.6. Confirming, Cancelling, and Expiring an Adoption

A pledge is not a commitment until the donor confirms it. Confirming — `PLEDGED → CONFIRMED` — is permitted only to the donor whose `X-User-ID` equals the adoption's `donor_id`, only within 72 hours of `pledged_at` (a later attempt yields `ERR_PLEDGE_EXPIRED`, HTTP 409), and only while the family is still `VERIFIED` (re-checked at confirm time) and the donor's concurrent-adoption count remains below `max_adoptions_per_season`. At confirm, the server stamps `confirmed_at`, snapshots `return_deadline` from the campaign's `gift_return_deadline`, cascades every covered child from `WISH_LOCKED` to `ADOPTED`, cascades every `APPROVED` wish item of those children to `COMMITTED`, transitions the family from `VERIFIED` to `MATCHED`, and increments both the family's and the adoption's `version`. Confirm additionally enforces a fiscal floor: `commitment_cents` must be at least the campaign's `min_gift_value_cents` multiplied by the number of covered children; otherwise the confirm is rejected with `ERR_COMMITMENT_TOO_LOW` (HTTP 422).

Once `CONFIRMED`, the adoption tracks gift arrival. The first gift that reaches `RECEIVED` under the adoption transitions it to `PARTIALLY_RECEIVED`. When every covered child has reached `DELIVERED`, `BACKFILL_PURCHASED`, or `CLOSED`, the adoption transitions to `FULFILLED`, whether from `CONFIRMED` or from `PARTIALLY_RECEIVED`.

A donor may cancel a `CONFIRMED` adoption. The cancel call takes an optional `reason`. If the current instant is at or before `return_deadline`, the adoption transitions `CONFIRMED → DONOR_CANCELLED`. If the current instant is past `return_deadline` and the donor supplies `reason` indicating a late cancellation, the adoption transitions `CONFIRMED → LATE_CANCELLED`; the donor remains `ACTIVE` but a strike is recorded via thank-you-note suppression. In both cases, no gift under the adoption may yet be in `RECEIVED`, `SORTED`, `STAGED`, or `DELIVERED`. Both cascades are identical: every gift in `COMMITTED` or `IN_TRANSIT` moves to `RETURNED_TO_DONOR`, every covered child in `ADOPTED` moves to `BACKFILL_ELIGIBLE`, every `COMMITTED` wish item of covered children reverts to `APPROVED`, and the family reverts from `MATCHED` to `VERIFIED` if no other confirmed adoption covers it (otherwise the family's state is recomputed from remaining adoptions).

A `PlatformAdmin` may force-cancel an adoption in `CONFIRMED` or `PARTIALLY_RECEIVED`, moving it to `ADMIN_CANCELLED`; the payload requires a `reason`. Gifts in `COMMITTED` or `IN_TRANSIT` move to `RETURNED_TO_DONOR`, gifts already in `RECEIVED` remain `RECEIVED` but are flagged, and covered children with no received gift move to `BACKFILL_ELIGIBLE`.

Two systematic expiry paths complete the lifecycle. A pledge that is not confirmed within 72 hours of `pledged_at` transitions to `EXPIRED`, leaving the family `VERIFIED` (no confirm cascade ever fired) and recomputing the referring agency's `referral_used_count`. And when the campaign advances past `gift_return_deadline` from `MATCHING` to `DISTRIBUTION_PREP` (§3.1), every adoption still in `PLEDGED` or `CONFIRMED` whose snapshotted `return_deadline` has passed moves to `EXPIRED`, cascading gifts in `COMMITTED` or `IN_TRANSIT` to `RETURNED_TO_DONOR`, children in `ADOPTED` to `BACKFILL_ELIGIBLE`, and recomputing the family state per any remaining confirmed adoptions.

### 3.7. Gift Declaration, Intake, Sorting, and Staging

A donor declares a gift under one of their own adoptions by posting a payload carrying `adoption_id`, `child_id`, an optional `wish_item_id`, a free-text `description`, and `declared_value_cents` (at least 0). Two validations guard the create. If `wish_item_id` is supplied, the referenced wish item's `child_id` must equal the gift's `child_id` and the wish item must be in `APPROVED` or `COMMITTED`; otherwise the create is rejected with `ERR_GIFT_WISH_MISMATCH` (HTTP 422). The declared value is audited against the campaign's per-item cap: `declared_value_cents` may not exceed `max_gift_value_cents`, else the create is rejected with `ERR_GIFT_VALUE_EXCEEDED` (HTTP 422). A gift begins in `COMMITTED`.

The donor marks a gift as shipped — `COMMITTED → IN_TRANSIT` — as long as the gift is still in `COMMITTED` and the caller's `X-User-ID` equals the adoption's `donor_id`.

Gift intake is performed by a `DistributionVolunteer`, who marks a gift as received. The receive call accepts an optional `override_note`. Receiving is permitted from either `COMMITTED` or `IN_TRANSIT`, but only inside the return window: the current instant must be at or before the adoption's snapshotted `return_deadline`, or — if `SeasonSettings.late_donor_grace_hours` is non-zero — within that many hours after the deadline and accompanied by a non-empty `override_note`. A violation is rejected with `ERR_RETURN_DEADLINE_PASSED` (HTTP 409). A successful receive stamps `received_at` and fans out a five-way cascade: the adoption moves from `CONFIRMED` to `PARTIALLY_RECEIVED` if this is its first gift; the child moves from `ADOPTED` to `GIFT_RECEIVED`; the referenced wish item moves from `COMMITTED` to `RECEIVED`; the family moves from `MATCHED` to `PARTIALLY_FULFILLED` with `fulfilled_children_count` recomputed; and the donor's `giving_history_cents` increases by the gift's `declared_value_cents`.

Once received, a gift may be sorted — `RECEIVED → SORTED` — provided the parent campaign is in `DISTRIBUTION_PREP` or `DISTRIBUTION` and at least one `DistributionEvent` under the campaign has reached `SORTING` or later. Sorting stamps `sorted_at`. A sorted gift may then be staged into a distribution slot — `SORTED → STAGED` — provided the target slot is in `RESERVED` or `CHECKED_IN`, the slot's `family_id` equals the gift's child's family, and the slot's event is in `SORTING`. A mismatch yields `ERR_STAGE_SLOT_MISMATCH` (HTTP 422). Staging sets the gift's `slot_id` and increments the slot's `gifts_staged_count`.

Two cancellation-side transitions return a gift to the donor without delivery. When an adoption transitions to any of `DONOR_CANCELLED`, `LATE_CANCELLED`, `ADMIN_CANCELLED`, or `EXPIRED`, every gift under it in `COMMITTED` or `IN_TRANSIT` moves to `RETURNED_TO_DONOR`. Separately, when a backfill purchase for the same wish item is marked purchased, any `COMMITTED` gift referencing that wish item moves to `BACKFILL_REPLACED`.

### 3.8. Backfill: Selector, Budget, and Purchase Lifecycle

When the gift-return deadline passes and unfulfilled adoptions expire, the children left in `ADOPTED` flip to `BACKFILL_ELIGIBLE` (§3.1, §3.6). A `PlatformAdmin` then runs the backfill child selector, supplying a `limit` for the maximum number of children to source in this batch. The selector scans for children in `BACKFILL_ELIGIBLE` whose family is in `MATCHED` or `PARTIALLY_FULFILLED` under this campaign, and scores each child as the sum of three terms. The first term is 100 multiplied by a priority weight, where the weight is eleven minus the child's smallest `priority_rank` among their `APPROVED` wish items, divided by ten — so a child whose most-wanted approved item has rank 1 contributes a weight of 1.0, while rank 10 contributes 0.1. The second term is an age-urgency score: 18 minus the child's age in years (computed per §3.4), multiplied by 2, so younger children are prioritized. The third term is the whole-day count between the family's `verified_at` and the current instant, capped at 30 days. The final score is rounded half-up to two decimal places. Children are ranked by score descending, with ties broken by the family's `verified_at` ascending and then by the child's `created_at` ascending. The selector walks the ranking top-down, creating one `BackfillPurchase` per selected child; if the budget is insufficient for a child's full wish list, that child is skipped and the selector continues down the ranking.

A `BackfillPurchase` begins in `ORDERED`, carrying `campaign_id`, `child_id`, `wish_item_id`, and the purchasing volunteer's `quoted_cost_cents` (at least 0). The campaign's `backfill_spent_cents` is the sum of `final_cost_cents` over purchases in `PURCHASED`; it starts at 0 and is the authoritative actual. A provisional remaining-budget projection is maintained alongside: the campaign's `backfill_budget_cents` minus `backfill_spent_cents` minus the sum of `quoted_cost_cents` over all purchases still in `ORDERED`. Quoted cost may differ from receipt cost, so the provisional is optimistic.

Marking a purchase purchased — `ORDERED → PURCHASED` — is performed by a `PlatformAdmin` who supplies the `final_cost_cents` from the receipt. Segregation of duties applies: the admin who created the purchase may not also mark it purchased (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). The authoritative budget check fires here: the campaign's `backfill_spent_cents` plus this `final_cost_cents` must not exceed `backfill_budget_cents`, else the mark is rejected with `ERR_BACKFILL_BUDGET_EXCEEDED` (HTTP 422). On success the server stamps `purchased_at` and `final_cost_cents`, adds `final_cost_cents` to the campaign's `backfill_spent_cents`, moves the child from `BACKFILL_ELIGIBLE` to `BACKFILL_PURCHASED` (terminal), moves the referenced wish item from `APPROVED` to `BACKFILL_SOURCED`, moves any `COMMITTED` gift referencing the same wish item to `BACKFILL_REPLACED`, and recomputes the family's rollup per sibling states (§3.10). An `ORDERED` purchase may instead be cancelled — `ORDERED → CANCELLED` — with no cascade. Once purchased, a `DistributionVolunteer` may sort it — `PURCHASED → SORTED` — provided the campaign is in `DISTRIBUTION_PREP` or `DISTRIBUTION`; and when the slot for the purchase's child's family completes, the purchase moves from `SORTED` to `DELIVERED` (§3.9).

### 3.9. Distribution Events, Slots, and Pickup Day

A `PlatformAdmin` creates a `DistributionEvent` with `campaign_id`, `site_name`, `start_at`, `end_at`, and `capacity_slots` (at least 1 and at most 1000). Window sanity is enforced: `end_at` must be strictly greater than `start_at`, else the create is rejected with `ERR_INVALID_WINDOW` (HTTP 422). An event begins in `PLANNED` and walks `PLANNED → OPEN_FOR_SLOTS → SORTING → LOCKED → COMPLETED`, with `CANCELLED` as a sibling terminal.

Opening slots — `PLANNED → OPEN_FOR_SLOTS` — requires the parent campaign to be in `DISTRIBUTION_PREP`. Beginning sorting — `OPEN_FOR_SLOTS → SORTING` — requires every slot under the event to have `window_start` at or after `start_at` and `window_end` at or before `end_at`. Locking — `SORTING → LOCKED` — requires that no gift staged into any of the event's slots remain in `RECEIVED` (all intake gifts must be either `SORTED` or `STAGED`, or explicitly excluded); after lock, no new stage calls are accepted for the event. Completing — `LOCKED → COMPLETED` — requires every slot under the event to be in `COMPLETED`, `NO_SHOW`, or `CANCELLED`. Cancelling the event — `PLANNED → CANCELLED` or `OPEN_FOR_SLOTS → CANCELLED` — cascades: every slot under the event in `RESERVED` or `CHECKED_IN` moves to `CANCELLED`, and any gift staged into those slots reverts to `SORTED` with its `slot_id` cleared.

Pickup slots are booked against an event by a `PlatformAdmin` or `DistributionVolunteer`. The create payload carries `event_id`, `family_id`, `window_start`, `window_end`, `lane` (one of `A`, `B`, `C`, `D`), and the OCC field `expected_event_version` (§2.7). A slot's window must lie within the parent event's window — `window_start` at or after `start_at` and `window_end` at or before `end_at`, with `window_end` strictly greater than `window_start` — else the create is rejected with `ERR_INVALID_WINDOW`. The slot's `family_id` must reference a family in `MATCHED`, `PARTIALLY_FULFILLED`, `FULFILLED`, or `BACKFILLED` under the same campaign as the event; otherwise the create is rejected with `ERR_SLOT_FAMILY_MISMATCH` (HTTP 422).

Two overlap rules govern slot creation and any later patch of a slot's window. On the family axis, no two slots for the same family may have overlapping half-open windows: a new slot `[window_start, window_end)` is rejected if there exists another slot for the same family (in any lane) whose `window_start` is strictly before the new slot's `window_end` and whose `window_end` is strictly after the new slot's `window_start`. Adjacent windows, where the new slot's `window_start` equals an existing slot's `window_end`, are permitted. A violation is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). On the lane axis, the timeline is divided into 30-minute buckets aligned to `:00` and `:30` UTC; within any such bucket, the count of slots in the same lane whose windows overlap the bucket must not exceed 4. A violation is rejected with `ERR_LANE_CAPACITY_EXCEEDED` (HTTP 409). A successful booking increments the parent event's `version`.

A slot begins in `RESERVED`. On pickup day, a `DistributionVolunteer` checks the family in — `RESERVED → CHECKED_IN` — provided the current instant is at or after `window_start` and at or before `window_end`; a check-in outside that window is rejected with `ERR_OUTSIDE_SLOT_WINDOW` (HTTP 409). If `window_end` elapses with no check-in, the slot transitions `RESERVED → NO_SHOW`, and any gifts staged into it revert to `SORTED` with `slot_id` cleared. A `PlatformAdmin` may cancel a `RESERVED` slot, which applies the same reversion of staged gifts.

Completing a checked-in slot — `CHECKED_IN → COMPLETED` — requires every gift with `slot_id` equal to this slot to be in `STAGED`. The completion cascade delivers the family's entire staged package: every gift staged into the slot moves from `STAGED` to `DELIVERED`, every child of the slot's family who is in `GIFT_RECEIVED` moves to `DELIVERED`, every `SORTED` backfill purchase for the family moves to `DELIVERED`, and the family's fulfillment rollup is recomputed. The corresponding wish items move from `RECEIVED` to `DELIVERED`.

### 3.10. Family Fulfillment Rollup and Terminal States

The family's `fulfilled_children_count` and `total_children_count` are maintained by a rollup that fires on every child status transition. `fulfilled_children_count` is the count of the family's children in `DELIVERED` or `BACKFILL_PURCHASED`. `total_children_count` is the count of the family's children not in `CLOSED`. The rollup also drives the family's status. When the fulfilled count is 0 and the family was in `MATCHED` or `PARTIALLY_FULFILLED`, the family returns to `MATCHED`. When the fulfilled count is strictly greater than 0 and strictly less than the total, the family is in `PARTIALLY_FULFILLED`. When the fulfilled count equals the total and the total is greater than 0, the family transitions to `FULFILLED` if every child arrived via `DELIVERED`, or to `BACKFILLED` if at least one child arrived via `BACKFILL_PURCHASED`. In state-pair terms, this defines four terminal-leaning transitions: `PARTIALLY_FULFILLED → FULFILLED`, `PARTIALLY_FULFILLED → BACKFILLED`, `MATCHED → FULFILLED` (a whole-family adoption whose every gift arrives in one scan batch), and `MATCHED → BACKFILLED` (the adoption expired with zero gifts received and every child was subsequently sourced from the central pool).

### 3.11. Post-Season: Thank-You Notes and Donor Retention

Once the campaign reaches `RECONCILIATION` or `CLOSED`, a `PlatformAdmin` may generate thank-you notes for the campaign. The generator walks every donor whose `giving_history_cents` is greater than 0 in this campaign and whose `thank_you_opt_in` is `true`, and selects a `template` per donor. If the donor's all-time `giving_history_cents` is at or above `SeasonSettings.major_donor_threshold_cents`, the template is `MAJOR_DONOR`. Otherwise, if the donor has never given in any prior season — no earlier campaign year with attributed gifts — the template is `FIRST_TIME`. Otherwise, if the donor's most recent gift before this campaign was two or more seasons ago, the template is `LAPSED_RETURNING`. Otherwise the template is `STANDARD`. Each generated note is `QUEUED` and carries a server-computed `personalization_token`: the SHA-256 hash of the donor's `id`, the campaign's `id`, and the template, rendered as hex and truncated to its first 16 characters, embedded in the letter for retention analytics.

Attempting generation while the campaign is not yet in `RECONCILIATION` or `CLOSED` is rejected with `ERR_CAMPAIGN_NOT_CLOSED` (HTTP 409). Sending a queued note — `QUEUED → SENT` — requires the donor's `thank_you_opt_in` to still be `true`; sending to an opted-out donor is rejected with `ERR_DONOR_OPTED_OUT` (HTTP 409). Send stamps `sent_at`. A queued note may instead be cancelled — `QUEUED → CANCELLED` — and a sent note that comes back undeliverable may be marked `SENT → BOUNCED`.

## 4. Endpoint Definitions

All endpoints live under the `/toy-drive` mount. A `POST` that creates a new resource returns HTTP 201; a `POST` that drives a state transition on an existing resource, a `PATCH`, or a `PUT` returns HTTP 200. All list endpoints return HTTP 200 with the paginated envelope described in §2.2 and §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /toy-drive/campaigns | Create a new campaign in DRAFT | PlatformAdmin |
| GET | /toy-drive/campaigns | List campaigns with pagination | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor, DistributionVolunteer |
| GET | /toy-drive/campaigns/{id} | Fetch one campaign | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor, DistributionVolunteer |
| PATCH | /toy-drive/campaigns/{id} | Edit campaign fields while DRAFT; distribution_date may shift while INTAKE_OPEN with child-age-band side effects | PlatformAdmin |
| POST | /toy-drive/campaigns/{id}/open-intake | DRAFT → INTAKE_OPEN | PlatformAdmin |
| POST | /toy-drive/campaigns/{id}/close-intake | INTAKE_OPEN → MATCHING; rejects incomplete families | PlatformAdmin |
| POST | /toy-drive/campaigns/{id}/advance | MATCHING → DISTRIBUTION_PREP → DISTRIBUTION → RECONCILIATION stepper with OCC | PlatformAdmin |
| POST | /toy-drive/campaigns/{id}/close | RECONCILIATION → CLOSED | PlatformAdmin |
| POST | /toy-drive/campaigns/{id}/backfill/select | Run the backfill child selector, creating BackfillPurchase rows in ORDERED status for the top-N eligible children | PlatformAdmin |
| POST | /toy-drive/campaigns/{id}/thank-you-notes/generate | Generate QUEUED ThankYouNote rows per donor for this campaign | PlatformAdmin |
| POST | /toy-drive/agencies | Register a partner agency | PlatformAdmin |
| GET | /toy-drive/agencies | List agencies | PlatformAdmin, CaseWorker, AgencyCoordinator |
| GET | /toy-drive/agencies/{id} | Fetch one agency | PlatformAdmin, CaseWorker, AgencyCoordinator |
| POST | /toy-drive/agencies/{id}/suspend | Suspend an agency; blocks new referrals | PlatformAdmin |
| GET | /toy-drive/agencies/{id}/families | List families referred by an agency | PlatformAdmin, CaseWorker, AgencyCoordinator |
| POST | /toy-drive/families | Submit a family referral | AgencyCoordinator |
| GET | /toy-drive/families | List families (filtered by campaign/agency/status); donors get PII-scrubbed view | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor |
| GET | /toy-drive/families/{id} | Fetch one family; donor role receives PII-scrubbed view | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor |
| GET | /toy-drive/families/{id}/children | List children of a family | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor |
| GET | /toy-drive/families/{id}/audit-events | List FamilyAuditEvent rows for a family | PlatformAdmin, CaseWorker |
| POST | /toy-drive/families/{id}/begin-review | REFERRED → UNDER_REVIEW | CaseWorker |
| POST | /toy-drive/families/{id}/verify | UNDER_REVIEW → VERIFIED; enforces segregation of duties vs begin-review actor | CaseWorker |
| POST | /toy-drive/families/{id}/reject | UNDER_REVIEW → REJECTED | CaseWorker |
| POST | /toy-drive/families/{id}/return-to-referral | UNDER_REVIEW → REFERRED (cyclic revision loop) | CaseWorker |
| POST | /toy-drive/families/{id}/withdraw | VERIFIED → WITHDRAWN when no active adoption exists | CaseWorker |
| POST | /toy-drive/families/{family_id}/children | Add a child to a family | AgencyCoordinator, CaseWorker |
| GET | /toy-drive/children/{id} | Fetch one child; donors get PII-scrubbed view | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor |
| GET | /toy-drive/children/{id}/gifts | List gifts targeting a child | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/children/{id}/wish-items | List wish items of a child | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor |
| POST | /toy-drive/children/{child_id}/wish-items | Add a wish item to a child | AgencyCoordinator, CaseWorker |
| GET | /toy-drive/wish-items/{id} | Fetch one wish item | PlatformAdmin, CaseWorker, AgencyCoordinator, Donor |
| GET | /toy-drive/wish-items/{id}/gifts | List gifts satisfying this wish item | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/wish-items/{id}/backfill-purchases | List backfill purchases sourcing this wish item | PlatformAdmin, CaseWorker, DistributionVolunteer |
| POST | /toy-drive/wish-items/{id}/approve | REQUESTED → APPROVED | CaseWorker |
| POST | /toy-drive/wish-items/{id}/reject | REQUESTED → REJECTED | CaseWorker |
| POST | /toy-drive/donors | Register a donor account | PlatformAdmin |
| GET | /toy-drive/donors | List donors (admin only — PII) | PlatformAdmin |
| GET | /toy-drive/donors/{id} | Fetch one donor; donors may only fetch themselves | PlatformAdmin, Donor |
| POST | /toy-drive/adoptions | Pledge an adoption (OCC on family version) | Donor |
| GET | /toy-drive/adoptions | List adoptions filtered by donor/campaign/family/status | PlatformAdmin, CaseWorker, Donor |
| GET | /toy-drive/adoptions/{id} | Fetch one adoption | PlatformAdmin, CaseWorker, Donor |
| GET | /toy-drive/adoptions/{id}/gifts | List gifts under an adoption | PlatformAdmin, CaseWorker, Donor, DistributionVolunteer |
| POST | /toy-drive/adoptions/{id}/confirm | PLEDGED → CONFIRMED with cascades to family/children/wish-items | Donor |
| POST | /toy-drive/adoptions/{id}/cancel | Donor cancels (DONOR_CANCELLED or LATE_CANCELLED depending on return_deadline) | Donor |
| POST | /toy-drive/adoptions/{id}/admin-cancel | Admin force-cancel | PlatformAdmin |
| POST | /toy-drive/gifts | Declare a gift under an adoption | Donor |
| GET | /toy-drive/gifts/{id} | Fetch one gift | PlatformAdmin, CaseWorker, Donor, DistributionVolunteer |
| POST | /toy-drive/gifts/{id}/ship | COMMITTED → IN_TRANSIT | Donor |
| POST | /toy-drive/gifts/{id}/receive | COMMITTED/IN_TRANSIT → RECEIVED with deadline + grace validation | DistributionVolunteer |
| POST | /toy-drive/gifts/{id}/sort | RECEIVED → SORTED | DistributionVolunteer |
| POST | /toy-drive/gifts/{id}/stage | SORTED → STAGED into a slot | DistributionVolunteer |
| GET | /toy-drive/backfill-purchases | Filtered list by campaign/child/wish-item/status | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/backfill-purchases/{id} | Fetch one backfill purchase | PlatformAdmin, CaseWorker, DistributionVolunteer |
| POST | /toy-drive/backfill-purchases/{id}/mark-purchased | ORDERED → PURCHASED; enforces segregation of duties vs creator and budget check | PlatformAdmin |
| POST | /toy-drive/backfill-purchases/{id}/cancel | ORDERED → CANCELLED | PlatformAdmin |
| POST | /toy-drive/backfill-purchases/{id}/sort | PURCHASED → SORTED | DistributionVolunteer |
| POST | /toy-drive/distribution-events | Create a distribution event | PlatformAdmin |
| GET | /toy-drive/distribution-events | List events | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/distribution-events/{id} | Fetch one event | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/distribution-events/{id}/slots | List slots under an event | PlatformAdmin, CaseWorker, DistributionVolunteer |
| POST | /toy-drive/distribution-events/{id}/open-slots | PLANNED → OPEN_FOR_SLOTS | PlatformAdmin |
| POST | /toy-drive/distribution-events/{id}/begin-sorting | OPEN_FOR_SLOTS → SORTING | PlatformAdmin |
| POST | /toy-drive/distribution-events/{id}/lock | SORTING → LOCKED | PlatformAdmin |
| POST | /toy-drive/distribution-events/{id}/complete | LOCKED → COMPLETED | PlatformAdmin |
| POST | /toy-drive/distribution-events/{id}/cancel | PLANNED/OPEN_FOR_SLOTS → CANCELLED with slot cascade | PlatformAdmin |
| POST | /toy-drive/distribution-slots | Book a pickup slot (OCC on event version) | PlatformAdmin, DistributionVolunteer |
| GET | /toy-drive/distribution-slots/{id} | Fetch one slot | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/distribution-slots/{id}/gifts | List gifts staged into this slot | PlatformAdmin, CaseWorker, DistributionVolunteer |
| GET | /toy-drive/families/{id}/distribution-slots | List pickup slots booked for a family | PlatformAdmin, CaseWorker, DistributionVolunteer |
| POST | /toy-drive/distribution-slots/{id}/check-in | RESERVED → CHECKED_IN within window | DistributionVolunteer |
| POST | /toy-drive/distribution-slots/{id}/complete | CHECKED_IN → COMPLETED; delivers all staged gifts | DistributionVolunteer |
| POST | /toy-drive/distribution-slots/{id}/cancel | RESERVED → CANCELLED | PlatformAdmin |
| GET | /toy-drive/duplicate-flags | Filtered list by family/other_family/status | PlatformAdmin, CaseWorker |
| GET | /toy-drive/duplicate-flags/{id} | Fetch one flag | PlatformAdmin, CaseWorker |
| POST | /toy-drive/duplicate-flags | Manually raise a duplicate flag between two families | CaseWorker |
| POST | /toy-drive/duplicate-flags/{id}/confirm | OPEN → CONFIRMED_DUPLICATE; rejects the duplicate family | CaseWorker |
| POST | /toy-drive/duplicate-flags/{id}/dismiss | OPEN → DISMISSED | CaseWorker |
| GET | /toy-drive/thank-you-notes | Filtered list by campaign/donor/status | PlatformAdmin |
| GET | /toy-drive/thank-you-notes/{id} | Fetch one note | PlatformAdmin |
| POST | /toy-drive/thank-you-notes/{id}/send | QUEUED → SENT | PlatformAdmin |
| POST | /toy-drive/thank-you-notes/{id}/cancel | QUEUED → CANCELLED | PlatformAdmin |
| POST | /toy-drive/thank-you-notes/{id}/mark-bounced | SENT → BOUNCED | PlatformAdmin |
| GET | /toy-drive/season-settings | Fetch the singleton settings row (auto-created with defaults on first GET) | PlatformAdmin |
| PUT | /toy-drive/season-settings | Update singleton settings (OCC) | PlatformAdmin |
| POST | /toy-drive/_clock/set_current_utc | Test-driving endpoint; sets the server's logical clock to an arbitrary ISO 8601 UTC instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_PRIVACY_VIOLATION | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_WINDOW | 422 |
| ERR_INTAKE_CLOSED | 409 |
| ERR_AGENCY_SUSPENDED | 409 |
| ERR_AGENCY_QUOTA_EXCEEDED | 409 |
| ERR_FAMILY_CHILD_CAP | 409 |
| ERR_CHILD_TOO_OLD | 422 |
| ERR_WISH_VALUE_EXCEEDED | 422 |
| ERR_DUPLICATE | 409 |
| ERR_DUPLICATE_FLAG_OPEN | 409 |
| ERR_PLEDGE_EXPIRED | 409 |
| ERR_ADOPTION_CAP_EXCEEDED | 409 |
| ERR_ADOPTION_COVERAGE_INVALID | 422 |
| ERR_COMMITMENT_TOO_LOW | 422 |
| ERR_RETURN_DEADLINE_PASSED | 409 |
| ERR_GIFT_WISH_MISMATCH | 422 |
| ERR_GIFT_VALUE_EXCEEDED | 422 |
| ERR_SLOT_OVERLAP | 409 |
| ERR_LANE_CAPACITY_EXCEEDED | 409 |
| ERR_SLOT_FAMILY_MISMATCH | 422 |
| ERR_STAGE_SLOT_MISMATCH | 422 |
| ERR_OUTSIDE_SLOT_WINDOW | 409 |
| ERR_BACKFILL_BUDGET_EXCEEDED | 422 |
| ERR_CAMPAIGN_NOT_CLOSED | 409 |
| ERR_DONOR_OPTED_OUT | 409 |
