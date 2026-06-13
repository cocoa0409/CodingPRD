# Pet Licensing & Animal Control API — Product Requirements Document

## 1. Introduction

Municipal animal-services departments juggle two intertwined mandates: issuing and renewing pet licenses (with the public-health checks that gate them), and enforcing animal-control law when a dog turns dangerous or an animal goes missing. Historically these have lived in separate ledgers, so a clerk approving a license rarely sees that the same dog carries an open dangerous-dog designation, and an owner who lets a license lapse can quietly accumulate unpaid penalties that never block a fresh application. This API unifies the two mandates behind one consistent set of records, so that vaccination proof, alteration status, dangerous-dog standing, fee accrual, and delinquency are all reconciled against a single source of truth.

The system models the full license lifecycle — from a draft application, through clerk review and rabies-proof verification, to tag issuance, renewal, grace, expiry, late-penalty settlement, and revocation — alongside the parallel lifecycles of dangerous-dog cases (with their appeal cycle) and lost-and-found reports (with reciprocal matching). Fees are computed twice: a *provisional* estimate stamped when an owner submits, and a *final* figure recomputed against verified facts when a clerk approves. Because a single enforcement action (a dangerous-dog designation, a deceased-pet report) can cascade across an owner's licenses, tags, and kennel occupancy, the design treats consistency as a first-class concern: every derived count and every dependent state is kept in lockstep with the events that drive it.

This document specifies the API's behavioral contract in full. It is written for the engineers who will implement the service and the reviewers who will verify it, and it is intended to be read end-to-end: business rules are described where they make narrative sense, which means a complete picture of any one endpoint is assembled from several sections.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `Owner`, `LicensingClerk`, and `AnimalControlOfficer`. When an authenticated caller attempts an operation their role is not permitted to perform — or attempts to act on a resource they do not own — the request is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how `X-User-ID` ties back to persisted data. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity; ownership checks on any resource that references an owner compare that resource's owning-owner foreign key to `X-User-ID`. Concretely, an `Owner` may only submit, attach proof to, renew, pay the penalty on, or otherwise act on a `License` whose `owner_id` equals their `X-User-ID`, and may only mark deceased or appeal a designation for a `Pet` whose `owner_id` equals their `X-User-ID`; a mismatch yields `ERR_UNAUTHORIZED`. When `X-User-Role` is `LicensingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, within the `actor_role` provenance written onto an `AuditEvent` by a transition) but never compares it to any entity's `id`. When `X-User-Role` is `AnimalControlOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded for audit provenance but never matched against an entity `id`. Section 4 enumerates which role or roles may invoke each endpoint; the per-operation breakdown of clerk-only, officer-only, and owner-only actions is woven through the workflow narratives of Section 3.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter sets how many items to skip from the front of the result set; it defaults to 0 and may not be negative. A request that supplies a `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the full count before pagination and `has_more` indicates whether further items remain beyond the current window.

### 2.4. Common Resource Properties and Record Mutability

Every primary resource carries a server-minted `id` formatted as a UUID, with no type prefix, generated by the server and never supplied by the client. Most resources additionally carry three system-managed timestamps and counters: `created_at`, an ISO 8601 UTC timestamp (with three fractional digits) marking creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that starts at its initial value and increments by one with every mutation of the resource. The owner, pet, kennel, license, tag, dangerous-dog case, and lost-and-found report records all carry this full set.

Two record types are deliberately immutable and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field. The first is the vaccination record, which is a proof artifact captured once and never edited. The second is the audit event, which is an append-only provenance entry. Whenever a write operation mutates a resource that does carry `version`, the server bumps that resource's `version` and refreshes its `updated_at`; this applies equally to changes in a derived field — when a designation cascade adjusts a license's `final_fee_cents`, or when settling a penalty recomputes an owner's `outstanding_penalty_cents`, those are mutations that advance `version` and `updated_at` on the affected record.

### 2.5. Nested Path Resolution and Reverse-Reachability Listings

Collections are flat and addressed at the top level; relationships between records are expressed through foreign-key fields carried in request bodies rather than through deep URL nesting. A number of read endpoints, however, expose a parent identifier in the path and return the children that reference it — an owner's pets, an owner's licenses, an owner's kennels, a pet's vaccination records, a pet's licenses, a pet's dangerous-dog cases, a pet's lost-and-found reports, a kennel's licenses, and a license's tags. For any such path, the server resolves identifiers left to right and rejects the request with `ERR_NOT_FOUND` against the first identifier in the path that does not name an existing record, before it evaluates any downstream rule. The same `ERR_NOT_FOUND` governs any foreign key named in a request body that points at a non-existent record.

### 2.6. Validation Ordering and Precedence

When several checks could fail for the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a request lacking valid headers or naming an unknown role fails with `ERR_UNAUTHENTICATED` (HTTP 401). Authorization is next — role permission for the operation, and, for an `Owner`, ownership of the target resource — failing with `ERR_UNAUTHORIZED` (HTTP 403). Existence checks follow, with every path and foreign-key-referenced record resolved left to right and a miss reported as `ERR_NOT_FOUND` (HTTP 404). Then comes request well-formedness: required fields present, enumerations in range, `term_years` one of the two permitted whole-year terms, and `slot_capacity` at least 1, any violation of which is `ERR_INVALID_REQUEST` (HTTP 400); for list endpoints specifically, the pagination-range check described in Section 2.3 raises `ERR_VALIDATION` (HTTP 400). Only after those gates does the system test whether the target resource is in a state from which the requested transition is defined, raising `ERR_INVALID_STATE` (HTTP 409) when it is not. Business-specific rules — license-kind coherence, vaccination matching, rabies proof, dangerous-dog holds, period overlap, kennel capacity, penalty settlement, owner delinquency — are evaluated after the generic state check, each with its own error as detailed throughout Section 3.

### 2.7. Fee, Surcharge, and Penalty Precision

All monetary amounts in this system are integers denominated in cents; there are no fractional-cent values stored or returned. Wherever a calculation introduces a non-integer intermediate (a multiplier applied to a base rate, a percentage discount), the result is rounded to a whole number of cents using the round-half-up convention — a value exactly halfway between two integers rounds upward. The fee calculation rounds at two pinned points, the surcharge rounds once and is then floored to a minimum, and the late penalty rounds once and is then capped; the exact sequencing for each is given in the relevant Section 3 narrative, because the order in which rounding is applied is part of the contract, not an implementation nicety.

### 2.8. Derived Counts and the Delinquency Invariant

Several fields are not supplied by clients but are continuously reconciled from the records that drive them. An owner's `active_license_count` is the number of that owner's licenses currently in `ACTIVE` status. An owner's `outstanding_penalty_cents` is the authoritative *net* balance of unpaid late penalties: the sum of `late_penalty_cents` over the owner's licenses that are in `EXPIRED` or `GRACE` status **and** whose `penalty_paid` flag is `false`. A license that has been moved to `EXPIRED` but whose penalty has since been settled in place (so its `penalty_paid` is `true`) is excluded from that sum even though it is still `EXPIRED`; the naive reading that would ignore `penalty_paid` and keep counting an already-settled penalty is wrong and over-states the balance. An owner is `DELINQUENT` exactly when this net outstanding balance is greater than zero, and `ACTIVE` again the moment it returns to zero. A kennel's `occupied_slots` is the number of that kennel's licenses currently in `ACTIVE` or `GRACE` status. Each of these is recomputed by the events that can change it — tag issuance, expiry, revocation, renewal, penalty settlement, and deceased-pet cascades — as described in Section 3.

### 2.9. Concurrency and Serial Observation

This API does not use client-supplied version tokens for concurrency control, and no write endpoint accepts an expected-version field. The reason is that every contended write in this domain is gated by an observable state precondition: a second attempt to issue a tag observes the license already in `ACTIVE` and is refused with `ERR_INVALID_STATE`; a second attempt to settle a penalty observes `penalty_paid` already `true` and is refused with `ERR_INVALID_STATE`; a second attempt to match an already-matched report observes it in `MATCHED` and is refused with `ERR_INVALID_STATE`. Because each follow-on request sees the flipped status or flag left by its predecessor, the ordinary state machine and validation rules are sufficient to serialize them, and no optimistic-concurrency version input is required anywhere in the API.

### 2.10. The Test-Driving Clock

Temporal rules in this system — vaccination expiry, grace windows, expiry, and late-penalty accrual — are evaluated against a logical "current time" rather than wall-clock time, so that time-dependent behavior is reproducible. Two administrative capabilities manipulate that clock by accepting a target instant in the `to_iso8601` field: one sets the logical current time to an absolute UTC instant, and the other advances it and re-evaluates the automatic license transitions described in Section 3. A third administrative seeding capability accepts a `kennel_id`, an `owner_id`, a `count`, and an optional `is_altered` flag, and synthesizes that many fully-active kennel licenses (each with its own pet and rabies proof) attached to the named kennel so that capacity and discount boundary states are reachable directly. These capabilities exist for test orchestration; Section 4 lists the roles permitted to invoke them.

## 3. Business Logic & Workflows

### 3.1. Owners, Pets, and Vaccination Proof

The root participant is the **owner**, registered with a `full_name`, an `email` (unique across owners), and a residential `address_zip` that the jurisdiction check reads. A freshly registered owner begins in `ACTIVE` standing, with both derived figures — `active_license_count` and `outstanding_penalty_cents` — at zero. An owner self-registers, or a clerk may register one on their behalf.

A **pet** belongs to one owner, recorded through the owning `owner_id` carried on the pet, alongside a `name`, a `species` of either `DOG` or `CAT`, a `breed` label, an `is_altered` flag stating whether the animal has been spayed or neutered (defaulting to `false` and driving the fee tier), and a `birth_date`. Two further fields are system-maintained rather than supplied: `is_dangerous`, which starts `false` and flips to `true` only once a dangerous-dog case for that pet reaches designation, and the pet's own `status`, which starts `ACTIVE` and can move once and only once to the terminal `DECEASED`. When an owner reports a pet deceased — an action only the pet's owner may take, and only while the pet is `ACTIVE` (otherwise `ERR_INVALID_STATE`) — the pet moves `ACTIVE → DECEASED` and a cascade fires: every license of that pet currently in `ACTIVE`, `GRACE`, or `APPROVED` is forced to `REVOKED`, its currently issued tag is voided, and the owner's `active_license_count` together with any affected kennel's `occupied_slots` is recomputed to reflect the licenses that just left their counted states.

Vaccination proof is recorded as an immutable **vaccination record** tied to a pet via `pet_id`, naming the `vaccine_type` (one of `RABIES`, `DHPP`, or `FVRCP`), the `administered_on` date, the `expires_on` date past which protection no longer holds, and the administering veterinarian's `vet_license_no`. Once written, a vaccination record is never modified; it is the artifact the licensing workflow consults whenever rabies proof must be demonstrated.

### 3.2. Kennels and the License Application

A **kennel** represents a multi-pet facility operated by an owner. It is created with the operator's `owner_id`, a `facility_name`, and a `slot_capacity` — the maximum number of pets that may be licensed under it, which must be at least 1. The kennel's `occupied_slots` is maintained by the system as described in Section 2.8 and begins at zero, and its `status` begins `OPEN`. An officer may suspend a kennel, moving its `status` to `SUSPENDED`, which blocks any new license from being attached to it; suspension is the officer's lever to freeze a facility.

A **license** is the central record. An application is created in `DRAFT` with the holder's `owner_id`, the licensed pet's `pet_id`, a `license_kind` of either `INDIVIDUAL` or `KENNEL`, and a `term_years` that must be a whole-year term of either 1 or 3. For a `KENNEL` license the `kennel_id` of the operating facility is supplied; for an `INDIVIDUAL` license the `kennel_id` is left null. At creation the license carries no fees — `provisional_fee_cents` and `final_fee_cents` and `late_penalty_cents` all sit at zero, `penalty_paid` at `false`, and `issued_on`, `expires_on`, `tag_serial`, and `vaccination_record_id` all null. As the license advances it walks the states `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_VACCINATION_PROOF`, `APPROVED`, `ACTIVE`, `GRACE`, `EXPIRED`, `REJECTED`, and `REVOKED`, of which `REJECTED` and `REVOKED` are terminal.

Submitting a draft — an action reserved to the license's owner, advancing it `DRAFT → SUBMITTED` — is where the application is first checked against reality. The acting owner must own the license, else `ERR_UNAUTHORIZED`. The pet must be `ACTIVE`, else `ERR_PET_NOT_ACTIVE`. The owner's own standing must be `ACTIVE`: a `DELINQUENT` owner may not submit any new application, and the attempt is refused with `ERR_OWNER_DELINQUENT`. License-kind coherence is enforced here as well — and it is the same rule applied at license creation. If the kind is `KENNEL`, a `kennel_id` must be present, the named kennel's `status` must be `OPEN`, and there must be a free slot, meaning the kennel's `occupied_slots` is strictly below its `slot_capacity`; a full kennel (occupied slots at or above capacity) yields `ERR_KENNEL_FULL`. If the kind is `INDIVIDUAL`, the `kennel_id` must be null. A kind/kennel mismatch — an `INDIVIDUAL` carrying a `kennel_id`, or a `KENNEL` whose kennel is missing or not `OPEN` — is rejected with `ERR_LICENSE_KIND_MISMATCH`. When all of these hold, submission stamps the license's `provisional_fee_cents` (the calculation is detailed in Section 3.6) and records the submission in the audit trail.

### 3.3. Clerk Review and the Rabies-Proof Cycle

Once an application is `SUBMITTED`, a `LicensingClerk` opens review, advancing it `SUBMITTED → UNDER_REVIEW`; the only precondition is that the license is in `SUBMITTED`, else `ERR_INVALID_STATE`. From `UNDER_REVIEW` the clerk has three onward moves. The clerk may request rabies proof, advancing `UNDER_REVIEW → NEEDS_VACCINATION_PROOF` (again gated only by the current state being `UNDER_REVIEW`, else `ERR_INVALID_STATE`). The clerk may reject the application outright, advancing `UNDER_REVIEW → REJECTED`, which is terminal and likewise requires the license to be `UNDER_REVIEW`. Or the clerk may approve it, advancing `UNDER_REVIEW → APPROVED`, discussed below.

When the application is in `NEEDS_VACCINATION_PROOF`, the ball is back with the owner, who attaches a vaccination record to advance it `NEEDS_VACCINATION_PROOF → UNDER_REVIEW`, returning the file to the clerk's queue. The attaching owner must own the license (`ERR_UNAUTHORIZED`). The supplied record is named by `vaccination_record_id` in the request, and three facts about it must hold, each with its own rejection. The record must belong to the same pet — its `pet_id` must equal the license's `pet_id` — or the attach is refused with `ERR_VACCINATION_MISMATCH`. The record's `vaccine_type` must be `RABIES`, else `ERR_RABIES_PROOF_REQUIRED`. And the record must still be in force, meaning its `expires_on` is strictly later than the current time; a record whose `expires_on` falls at or before now is refused with `ERR_VACCINATION_EXPIRED`. On success the license's `vaccination_record_id` is set and the application returns to `UNDER_REVIEW`, from which the clerk may cycle through another proof request if needed.

Approval, the clerk's move from `UNDER_REVIEW → APPROVED`, requires three things together: the license must be in `UNDER_REVIEW` (`ERR_INVALID_STATE`); a rabies proof must be on file and still valid, meaning the license's `vaccination_record_id` is set and that record is a `RABIES` record whose `expires_on` is later than the current time, failing which the approval is refused with `ERR_RABIES_PROOF_REQUIRED`; and the pet must still be `ACTIVE`, else `ERR_PET_NOT_ACTIVE`. Approval recomputes and stamps the license's `final_fee_cents` from verified facts (Section 3.6) and records the approval.

### 3.4. Tag Issuance, the Validity Period, and Revocation

A `LicensingClerk` issues the tag that brings a license to life, advancing it `APPROVED → ACTIVE`. The license must be `APPROVED`, else `ERR_INVALID_STATE`. Two safety gates apply. First, the pet must not be under a live dangerous-dog hold: issuance is permitted only when the pet's `is_dangerous` is `false`, or when any dangerous-dog case that existed for the pet now sits in `OVERTURNED` or `DISMISSED` — a pet carrying an open `DESIGNATED` case cannot have a tag issued, and the attempt fails with `ERR_DANGEROUS_DOG_HOLD`. Second, the new license period must not collide with another live license for the same pet: there must be no other license of the same pet in `ACTIVE` or `GRACE` whose validity interval, running from its `issued_on` up to but not including its `expires_on`, overlaps the interval this issuance would create, which runs from the current time up to but not including the current time plus `term_years`. The intervals are half-open, so a prior license whose `expires_on` lands exactly at the current instant is adjacent rather than overlapping and does not block issuance; a genuine overlap is rejected with `ERR_LICENSE_PERIOD_OVERLAP`.

When issuance succeeds, several things happen together. The server mints a **tag** — a record carrying the owning `license_id`, a server-minted `serial` assigned in monotonic issuance order, a `status` that begins `ISSUED`, and an `issued_on` timestamp — and copies that serial onto the license's `tag_serial`. The license's own `issued_on` is set to the current time and its `expires_on` is set to that `issued_on` plus `term_years`. The owner's `active_license_count` is recomputed now that this license is `ACTIVE`, and if the license belongs to a kennel, that kennel's `occupied_slots` is recomputed as well. The issuance is recorded in the audit trail.

Revocation is the `AnimalControlOfficer`'s enforcement lever. The officer may revoke a license that is in `ACTIVE` or in `GRACE`, advancing it to the terminal `REVOKED`; from any other state the request fails with `ERR_INVALID_STATE`. Revocation voids the license's current tag (its tag `status` becomes `VOID`) and recomputes the owner's `active_license_count` and, for a kennel license, the kennel's `occupied_slots`, since the license has left its counted state.

A tag's lifecycle therefore tracks the license: it is `ISSUED` while current, becomes `SUPERSEDED` when a renewal mints its replacement, and becomes `VOID` when the license is revoked.

### 3.5. Grace, Expiry, Penalties, Settlement, and Renewal

Licenses age against the logical clock. When the clock advances past a license's `expires_on` while still within the grace window — that is, the current time is at or after `expires_on` but strictly before `expires_on` plus the grace window of 30 days — the license auto-transitions `ACTIVE → GRACE`. This evaluation runs automatically whenever the clock advances, with no per-license request. Renewing from grace, an owner-only action advancing `GRACE → ACTIVE`, requires the owner to own the license (`ERR_UNAUTHORIZED`), the license to be in `GRACE` (`ERR_INVALID_STATE`), and a current `RABIES` vaccination record for the pet that is unexpired against the current time (`ERR_RABIES_PROOF_REQUIRED`); a renewal out of `GRACE` carries no late penalty, because penalty only accrues at expiry. Such a renewal mints a replacement tag, marks the prior tag `SUPERSEDED`, points the license's `tag_serial` at the new serial, and sets the license's `expires_on` to the current time plus `term_years`.

If the clock advances past the end of the grace window — the current time reaching or passing `expires_on` plus 30 days — the license auto-transitions `GRACE → EXPIRED`. Expiry stamps the late penalty onto `late_penalty_cents` (Section 3.6), sets `penalty_paid` to `false`, recomputes the owner's net `outstanding_penalty_cents`, and if that balance is now above zero sets the owner's `status` to `DELINQUENT`. The owner's `active_license_count` is recomputed (the license is no longer `ACTIVE`) and, for a kennel license, the kennel's `occupied_slots` is recomputed too.

An owner with an expired license has two ways forward. They may settle the fine without renewing, a self-loop that keeps the license in `EXPIRED`: the owner must own the license (`ERR_UNAUTHORIZED`), the license must be `EXPIRED` (`ERR_INVALID_STATE`), its `penalty_paid` must still be `false` (a second settlement attempt, seeing `penalty_paid` already `true`, is refused with `ERR_INVALID_STATE`), and the supplied `pay_penalty_cents` must settle the penalty in full, equalling the license's `late_penalty_cents` exactly — anything short is `ERR_PENALTY_UNPAID`. Settlement sets `penalty_paid` to `true` while the license stays `EXPIRED`, recomputes the owner's net `outstanding_penalty_cents` (this license now drops out of the net sum because its penalty is paid even though it is still `EXPIRED`), and clears the owner back to `ACTIVE` standing if that balance has reached zero.

Alternatively, the owner may renew straight out of expiry, advancing `EXPIRED → ACTIVE`. This requires owning the license (`ERR_UNAUTHORIZED`), the license being `EXPIRED` (`ERR_INVALID_STATE`), a current unexpired `RABIES` proof for the pet (`ERR_RABIES_PROOF_REQUIRED`), and the penalty being settled — either `penalty_paid` is already `true`, or the request settles it now with `pay_penalty_cents` equal to the license's `late_penalty_cents` in full; an unsettled penalty blocks the renewal with `ERR_PENALTY_UNPAID`. A successful renewal-from-expiry marks `penalty_paid` `true`, mints a replacement tag and supersedes the prior one with the new `tag_serial`, sets `expires_on` to the current time plus `term_years`, recomputes the owner's net `outstanding_penalty_cents` (returning the owner to `ACTIVE` standing if it reaches zero), and recomputes `active_license_count` and any kennel's `occupied_slots` now that the license is `ACTIVE` again.

### 3.6. How Fees, Surcharges, and Penalties Are Computed

The **license fee** is computed in stages and exists in two variants. Begin from a base rate chosen by license kind: an `INDIVIDUAL` license starts from 40 dollars (4000 cents) and a `KENNEL` license from 120 dollars (12000 cents) of per-pet base. That base is multiplied by an alteration factor — one-half (0.5) when the pet is altered, and the full factor of one (1.0) when it is not — and the product is rounded half-up to whole cents at this first point. For a `KENNEL` license a multi-pet discount is then applied: each occupied slot shaves five percent (0.05) off, so the discount percentage is five percent multiplied by the kennel's occupied-slot count (treated as zero if somehow negative), but the discount is capped so that the discounted fee never falls below sixty percent of the un-discounted fee — equivalently, the discount percentage is the smaller of (five percent times occupied slots) and forty percent (which is one minus the sixty-percent floor). The fee after multiplying by one-minus-that-discount is rounded half-up to whole cents a second time; this second rounding happens after the discount, and the order of the two roundings is fixed. Finally, for the *final* variant only, if the pet is dangerous at the time of computation, the dangerous-dog surcharge is added as a flat number of cents after all rounding, with no further rounding applied.

The two variants differ in their inputs. The **provisional** variant is stamped when the owner submits (`DRAFT → SUBMITTED`); it reads `is_altered` as declared on the application at that moment and the kennel's occupied slots as of submission, and it never includes any dangerous-dog surcharge. The **final** variant is recomputed when the clerk approves (`UNDER_REVIEW → APPROVED`); it reads the pet's verified `is_altered` and adds the dangerous-dog surcharge when the pet's `is_dangerous` is true at approval time. The two figures can legitimately diverge — for instance when alteration was mis-declared, or when a designation landed between submission and approval — which is exactly why the provisional figure is an estimate and the final figure is authoritative.

The **dangerous-dog surcharge** is computed once, at designation. Start from a base surcharge of 50 dollars (5000 cents) and scale it by a severity multiplier: a `BITE` multiplies by one (1.0), an `ATTACK` by two (2.0), and a `NUISANCE` by one-half (0.5). Round that product half-up to whole cents, then floor it at a minimum of 30 dollars (3000 cents), so even a `NUISANCE` designation never produces a surcharge below 3000 cents. The resulting amount is recorded on the case's `surcharge_cents`.

The **late penalty** is computed at the instant a license expires (`GRACE → EXPIRED`). Count the whole days late from the end of the grace window — that is, from `expires_on` plus the 30-day grace period — by taking the elapsed time since that moment and flooring it to a whole number of days. Choose the daily rate by tier: if the days late are at most 30, the rate is 2 dollars (200 cents) per day; once the days late exceed 30, the rate is 5 dollars (500 cents) per day. The boundary is inclusive of the first tier — exactly 30 days late still uses the 200-cents-per-day rate, and 31 days late uses the 500-cents rate. Multiply days late by the chosen per-day rate, round half-up to whole cents, and then cap the result at the license's own `final_fee_cents`, so a license's penalty can never exceed its own final fee. The capped result is stamped onto `late_penalty_cents`.

The **owner outstanding balance** stamped onto `outstanding_penalty_cents` is the net reading defined in Section 2.8: summed over the owner's own licenses, including only those in `EXPIRED` or `GRACE` status whose `penalty_paid` is `false`, of each such license's `late_penalty_cents`. It is recomputed whenever one of the owner's licenses enters `EXPIRED`, settles its penalty via the expired self-loop, or renews out of `EXPIRED`, and the owner is flagged `DELINQUENT` exactly when this net total exceeds zero.

### 3.7. Dangerous-Dog Cases and the Designation Cascade

An `AnimalControlOfficer` opens a **dangerous-dog case** against a pet, supplying the subject `pet_id`, an `incident_summary` describing what happened, and a `severity` of `BITE`, `ATTACK`, or `NUISANCE`. The case opens in `REPORTED`. The case carries a system-maintained `surcharge_cents` (zero until designation) and walks the states `REPORTED`, `INVESTIGATING`, `DESIGNATED`, `APPEALED`, `OVERTURNED`, and `DISMISSED`, of which `OVERTURNED` and `DISMISSED` are terminal.

The officer begins investigation, advancing `REPORTED → INVESTIGATING` (only from `REPORTED`, else `ERR_INVALID_STATE`). From investigation the case forks. The officer may dismiss it, advancing `INVESTIGATING → DISMISSED` (only from `INVESTIGATING`, else `ERR_INVALID_STATE`). Or the officer may designate the dog as dangerous, advancing `INVESTIGATING → DESIGNATED`, which requires the case be in `INVESTIGATING` (`ERR_INVALID_STATE`) and that no other case for the same pet already sits in `DESIGNATED` — a duplicate live designation is refused with `ERR_ALREADY_DESIGNATED`.

Designation triggers a two-hop cascade that is the heart of this workflow. First, the case's `surcharge_cents` is computed (Section 3.6). Then, hop one, the pet's `is_dangerous` flag is set to `true`. Hop two fans out across the pet's licenses: for each license of that pet currently in `ACTIVE` or `GRACE`, the case's surcharge is added to that license's `final_fee_cents` (the license's `expires_on` is left unchanged). Each such license keeps its current status — it remains `ACTIVE` — but now carries the added surcharge, which becomes payable at the license's next renewal. The designation is recorded in the audit trail.

The owner may contest a designation. Appealing, an owner-only action advancing `DESIGNATED → APPEALED`, requires the acting owner to own the pet (`ERR_UNAUTHORIZED`) and the case to be in `DESIGNATED` (`ERR_INVALID_STATE`). From `APPEALED` the officer resolves the appeal one of two ways. Upholding it advances `APPEALED → DESIGNATED`; the surcharge was already applied at the original designation and is not applied a second time, so upholding simply returns the case to `DESIGNATED` without touching fees. Overturning it advances `APPEALED → OVERTURNED` (terminal) and runs a compensating reversal that must exactly undo the designation's fee contribution: if no *other* case for the pet remains `DESIGNATED`, the pet's `is_dangerous` is cleared back to `false` (hop one), and for each license of that pet in `ACTIVE` or `GRACE` that is carrying this case's surcharge, that surcharge is subtracted back out of the license's `final_fee_cents` (hop two), so the net surcharge contribution returns to zero. Both appeal outcomes require the case to be in `APPEALED`, else `ERR_INVALID_STATE`, and both are recorded in the audit trail.

### 3.8. Lost-and-Found Reports and Reciprocal Matching

Anyone in the system — an owner, an officer, or a clerk — may file a **lost-and-found report**. It records a `report_type` of `LOST` or `FOUND`, a `species` of `DOG` or `CAT`, the `zip_seen` where the animal was lost or sighted, and a `reported_at` timestamp of the loss or sighting. A `LOST` report filed by an owner names the missing pet via `pet_id`; a `FOUND` report leaves `pet_id` null. A `FOUND` report may additionally carry a `tag_serial_seen` read off the found animal's tag (null if no tag was visible). Every report opens in `OPEN`, walks the states `OPEN`, `MATCHED`, `RESOLVED`, and `CLOSED` (`CLOSED` is terminal), and carries two system-maintained fields: `matched_report_id`, the identifier of the counterpart report it is matched to (the relationship is self-referential among reports), and `match_score`, the score of the chosen counterpart at match time.

An `AnimalControlOfficer` drives matching. Matching a report advances it `OPEN → MATCHED`; the report must be `OPEN` (`ERR_INVALID_STATE`), and there must exist at least one viable counterpart, failing which the request is refused with `ERR_NO_MATCH_CANDIDATE`. To choose the counterpart, the system scores every `OPEN` report of the *opposite* `report_type` (a `LOST` report is matched against `FOUND` candidates and vice versa, with the report being matched itself excluded). Each candidate's score starts at zero and accrues signals: 10 points if the candidate's `species` equals this report's `species`; 20 points if the candidate's `zip_seen` equals this report's `zip_seen`; and 100 points if both reports carry a non-null `tag_serial_seen` and those serials are equal — an exact tag-serial agreement is decisive on its own, while species-plus-zip agreement is the next-best signal. Only candidates whose score is at least 20 — the minimum that requires at least a ZIP-level agreement — are eligible. If no candidate reaches that floor, the match fails with `ERR_NO_MATCH_CANDIDATE`. Among the eligible candidates the winner is the one with the highest score; ties are broken first by the earlier `reported_at`, and if still tied by the earlier `created_at` (never by `id`).

When a match lands, the relationship is made mutual: this report's `matched_report_id` is set to the winner and the winner's `matched_report_id` is set back to this report, the winner's `status` is set to `MATCHED`, and both reports' `match_score` is set to the winning score. The match is recorded in the audit trail. A match can be undone: unmatching advances `MATCHED → OPEN`, requires the report to be `MATCHED` (`ERR_INVALID_STATE`), resets this report's `matched_report_id` to null and its `match_score` to zero, and applies the same compensating reversal to the counterpart — returning it to `OPEN` with its `matched_report_id` nulled and its `match_score` zeroed — so the pair becomes re-matchable.

A matched pair is resolved together: resolving advances `MATCHED → RESOLVED`, requires the report to be `MATCHED` (`ERR_INVALID_STATE`), and cascades the same move onto the matched counterpart, setting its `status` to `RESOLVED` as well. Finally, a report may be closed: closing advances either an `OPEN` report or a `RESOLVED` report to the terminal `CLOSED`, requiring respectively that the report be `OPEN` or `RESOLVED` (otherwise `ERR_INVALID_STATE`).

### 3.9. The Audit Trail

Every state transition across licenses, dangerous-dog cases, and lost-and-found reports appends an immutable **audit event**. Each event records the `subject_entity` it concerns — one of `LICENSE`, `DANGEROUS_DOG_CASE`, or `LOST_FOUND_REPORT` — the `subject_id` of the specific row it concerns (a polymorphic reference, since the target type varies), the `action` name of the transition or operation recorded (for example a license approval, a dog designation, or a report match), and the `actor_role` that performed it. Audit events are append-only and may be listed and filtered by `subject_entity` and `subject_id`; clerks and officers may read the trail.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and every administrative clock or seeding capability — return a `200 OK` status code. Request bodies, response bodies, and side effects are described in Section 3; the table below gives only the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/owners` | Register an Owner | LicensingClerk, Owner |
| GET | `/owners/{id}` | Get an Owner with computed counts | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/owners/{id}/pets` | List an owner's pets | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/owners/{id}/licenses` | List an owner's licenses | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/owners/{id}/kennels` | List an owner's kennels | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/pets` | Create a Pet | Owner, LicensingClerk |
| GET | `/pets/{id}` | Get a Pet | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/pets/{id}/mark-deceased` | Mark a pet deceased; revoke its non-terminal licenses | Owner |
| GET | `/pets/{id}/vaccination-records` | List a pet's vaccination records | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/pets/{id}/licenses` | List a pet's licenses | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/pets/{id}/dangerous-dog-cases` | List a pet's dangerous-dog cases | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/pets/{id}/lost-found-reports` | List a pet's lost/found reports | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/vaccination-records` | Record a vaccination proof | Owner, LicensingClerk |
| GET | `/vaccination-records/{id}` | Get a vaccination record | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/kennels` | Create a Kennel facility | Owner, LicensingClerk |
| GET | `/kennels/{id}` | Get a Kennel | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/kennels/{id}/licenses` | List a kennel's licenses | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/kennels/{id}/suspend` | Suspend a kennel | AnimalControlOfficer |
| POST | `/licenses` | Create a license application in DRAFT | Owner, LicensingClerk |
| GET | `/licenses/{id}` | Get a License | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/licenses` | List licenses with filters | LicensingClerk, AnimalControlOfficer, Owner |
| POST | `/licenses/{id}/submit` | Submit application; stamp provisional fee | Owner |
| POST | `/licenses/{id}/start-review` | Begin review | LicensingClerk |
| POST | `/licenses/{id}/request-vaccination-proof` | Request rabies proof | LicensingClerk |
| POST | `/licenses/{id}/attach-vaccination` | Attach rabies proof | Owner |
| POST | `/licenses/{id}/approve` | Approve; stamp final fee | LicensingClerk |
| POST | `/licenses/{id}/reject` | Reject the application | LicensingClerk |
| POST | `/licenses/{id}/issue-tag` | Issue tag; activate the license | LicensingClerk |
| POST | `/licenses/{id}/renew` | Renew from GRACE or EXPIRED | Owner |
| POST | `/licenses/{id}/pay-penalty` | Settle an EXPIRED license's late penalty | Owner |
| POST | `/licenses/{id}/revoke` | Revoke a license | AnimalControlOfficer |
| GET | `/licenses/{id}/tags` | List a license's tags | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/dangerous-dog-cases` | Open a dangerous-dog case | AnimalControlOfficer |
| GET | `/dangerous-dog-cases/{id}` | Get a dangerous-dog case | LicensingClerk, Owner, AnimalControlOfficer |
| POST | `/dangerous-dog-cases/{id}/investigate` | Begin investigation | AnimalControlOfficer |
| POST | `/dangerous-dog-cases/{id}/designate` | Designate as dangerous; cascade surcharge | AnimalControlOfficer |
| POST | `/dangerous-dog-cases/{id}/dismiss` | Dismiss the case | AnimalControlOfficer |
| POST | `/dangerous-dog-cases/{id}/appeal` | Appeal a designation | Owner |
| POST | `/dangerous-dog-cases/{id}/overturn` | Overturn on appeal; reverse surcharge | AnimalControlOfficer |
| POST | `/dangerous-dog-cases/{id}/uphold` | Uphold on appeal | AnimalControlOfficer |
| POST | `/lost-found-reports` | File a lost or found report | Owner, AnimalControlOfficer, LicensingClerk |
| GET | `/lost-found-reports/{id}` | Get a lost/found report | LicensingClerk, Owner, AnimalControlOfficer |
| GET | `/lost-found-reports` | List lost/found reports with filters | LicensingClerk, AnimalControlOfficer, Owner |
| POST | `/lost-found-reports/{id}/match` | Match to the best counterpart | AnimalControlOfficer |
| POST | `/lost-found-reports/{id}/resolve` | Resolve a matched pair | AnimalControlOfficer |
| POST | `/lost-found-reports/{id}/unmatch` | Unmatch a matched pair | AnimalControlOfficer |
| POST | `/lost-found-reports/{id}/close` | Close a report | AnimalControlOfficer |
| GET | `/audit-events` | List audit events with filters | LicensingClerk, AnimalControlOfficer |
| POST | `/_clock/set` | Set the system clock to an absolute instant | LicensingClerk, AnimalControlOfficer |
| POST | `/_clock/advance` | Advance the clock; fire auto-transitions | LicensingClerk, AnimalControlOfficer |
| POST | `/_bulk/seed-kennel-licenses` | Synthesize active kennel licenses for testing | LicensingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LICENSE_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VACCINATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VACCINATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RABIES_PROOF_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DANGEROUS_DOG_HOLD` | 422 Unprocessable Entity |
| `ERR_ALREADY_DESIGNATED` | 409 Conflict |
| `ERR_KENNEL_FULL` | 409 Conflict |
| `ERR_LICENSE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PENALTY_UNPAID` | 402 Payment Required |
| `ERR_OWNER_DELINQUENT` | 409 Conflict |
| `ERR_PET_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_MATCH_CANDIDATE` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
