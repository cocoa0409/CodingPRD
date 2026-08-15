# Dog Park Membership API — Product Requirements Document

## 1. Introduction

Municipal and private dog parks run on trust: every animal through the gate is vaccinated, licensed, and matched to the right size area, and every handler on the path is a member in good standing. The Dog Park Membership API, mounted under `/dog-park`, is the operational backbone for such a facility. It governs the complete membership lifecycle — registration, dog document verification, annual fee payment, renewal, suspension, and reinstatement — while simultaneously running the day-to-day realities of the park itself: gate check-ins under capacity and peak-hour limits, sponsored guest passes, maintenance closures, waste-station servicing, and the incident pipeline that protects the community from aggressive animals and repeat offenders.

Two design commitments shape everything that follows. First, enforcement is immediate and atomic: when an incident report is confirmed and a member crosses the suspension threshold, the membership suspension, the force-closed visits, and the voided guest passes all land inside the triggering request. Second, the system never consults wall-clock time for business rules — every temporal decision reads a logical clock that administrators control, so behavior stays deterministic and auditable across registration peaks, renewal season, and nightly maintenance epochs. Section 2 specifies the global contracts, Section 3 the business workflows, Section 4 the endpoint surface, and Section 5 the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. Four roles are recognized: `Anonymous`, `Member`, `Steward`, and `ParkAdmin`. A request missing either header, or presenting a role outside these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed among the endpoint's authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member; ownership checks on any resource that references a Member — a dog's `member_id`, a membership's `member_id`, a guest pass's `sponsor_member_id`, a visit's `member_id` — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). When `X-User-Role` is `Steward`, `X-User-ID` is likewise the `id` of a Member, and additionally that member's `is_steward` flag must be true; a steward-role request from a member without the flag — or from an `X-User-ID` that matches no persisted member at all — fails with `ERR_NOT_A_STEWARD` (HTTP 403). When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque registrant identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and the role carries exactly one capability — registering a new member account. When `X-User-Role` is `ParkAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and where an administrator action would otherwise capture a caller identity — such as an incident report's `reporter_member_id` — the field is recorded as null. `ParkAdmin` is a hierarchical superset of every other role's capabilities and is exempt from both ownership checks and the steward-flag gate.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0, with a minimum of 0. Both parameters must parse as integers; a non-integer value or an integer outside these bounds is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with creation (insertion) order breaking ties between resources stamped at the same logical instant. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Calendar Semantics

Every temporal business rule — vaccination expiry, guest-pass validity, membership term expiry, closure windows, peak windows, monthly allotments — reads a server-held logical clock, never wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z; before any administrator sets it, all rules evaluate against that instant, and the clock never falls back to wall-clock time. A `ParkAdmin` advances the clock through the test-driving capability listed in §4 by supplying a `to_iso8601` instant; the capability responds with the new `current_utc` and mutates no entity. The target may be any valid instant, earlier or later than the current reading — no monotonicity check applies. Every timestamp the server emits — the envelope's `api_request_timestamp`, every resource's `created_at` and `updated_at`, and stamps such as `checked_in_at`, `checked_out_at`, and `last_serviced_at` — reads this same logical clock. Wherever an input must be a full instant (`to_iso8601`, a closure's `starts_at` and `ends_at`, a report's `occurred_at`), the string must carry an explicit timezone designator (`Z` or a numeric offset); a timezone-less string is rejected with `ERR_INVALID_REQUEST`.

Date-typed and datetime-typed fields are distinct throughout this document. Fields documented as ISO dates carry a calendar day (`YYYY-MM-DD`) and compare against the current logical date, while datetime fields carry full ISO 8601 UTC instants and compare against the current logical time.

### 2.5. Common Resource Properties

All nine resources — Member, Dog, Membership, GuestPass, ParkArea, AreaClosure, ParkVisit, IncidentReport, and WasteStation — share one set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation.
- `version` (integer): begins at 1 when the resource is created and increments by exactly one on every mutation — including state transitions, derived-field recomputations, and changes driven by cascades or the nightly run.

### 2.6. Optimistic Concurrency Control

Two write endpoints are version-guarded, and they are the only ones in the API. Updating a member profile (`PATCH /dog-park/members/{memberId}`) requires `expected_member_version` as a non-optional input carrying the client's last-observed `version` of the Member; if the member's current `version` no longer matches, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never silently overwrites profile fields it never saw. Renewing a membership (`POST /dog-park/memberships/{membershipId}/renew`) requires `expected_membership_version` matched against the Membership's current `version`; because successive early renewals legitimately extend the term by one year each, a renewal carrying a stale version would silently double-extend the term, and it is instead rejected with `ERR_STALE_VERSION` (HTTP 412). On both endpoints the version check is evaluated before any resource-state rule (§2.7). No other endpoint accepts a version field.

### 2.7. Validation Order and Request Adjudication

Every request is adjudicated against a fixed priority pipeline, and a failure at any stage stops the pipeline and surfaces that stage's error. The stages, in order:

1. **Headers** — both context headers present and the role declared: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the caller's role is listed for the endpoint: `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Steward gate** — `X-User-Role: Steward` requires the caller member's `is_steward` to be true: `ERR_NOT_A_STEWARD`.
4. **Ownership** — a `Member`-role caller acts only on their own resources: the path `memberId` equals `X-User-ID`; the addressed dog, membership, pass, or visit belongs to `X-User-ID`; a guest-pass list's sponsor filter equals `X-User-ID` or is auto-scoped to it: `ERR_NOT_OWNER`. Ownership against a path `memberId` is a pure string comparison and fires at this stage, before any shape or existence work; ownership that can only be judged against a fetched entity — a dog, membership, guest pass, or visit — is evaluated the moment that entity's existence check passes, so a Member-role caller addressing a nonexistent entity hears its 404, never `ERR_NOT_OWNER`.
5. **Request shape** — required fields present, enum values valid, exactly one of `dog_id` and `guest_pass_id` supplied at check-in, `ends_at` strictly after `starts_at`, `peak_capacity` not exceeding `capacity`, pagination parameters within bounds: `ERR_INVALID_REQUEST`. Required string fields must additionally be non-empty; fields beyond those documented for an endpoint are ignored rather than rejected; and a list-filter value that fails to parse or names no member of the documented enum is likewise `ERR_INVALID_REQUEST`.
6. **Existence** — path identifiers exist, validated left to right (§2.8), and identifiers referenced in the request body are validated in the order the endpoint narrative introduces them — at check-in the `area_id` first, then the `dog_id` or `guest_pass_id`; at incident filing the subject member, then the optional subject dog, then the optional area: the 404 family.
7. **Optimistic concurrency** — `expected_member_version` or `expected_membership_version` matches the entity's current `version`: `ERR_STALE_VERSION`.
8. **State preconditions** — the resource sits in a status from which the requested transition is defined; for renewal, the member-state check (member `ACTIVE` for early renewal, `LAPSED` for lapsed renewal) is evaluated before the membership-state check: the 409 state family.
9. **Vaccination currency** — `vaccination_expires_on` is on or after the current logical date at dog verification, at resubmission, and at check-in: `ERR_VACCINATION_EXPIRED`.
10. **Business constraints** — size-class agreement between dog or pass and area, at most one `OPEN` visit per dog, no self-reporting of incidents: `ERR_DOG_SIZE_AREA_MISMATCH`, `ERR_ALREADY_CHECKED_IN`, `ERR_SELF_REPORT_NOT_ALLOWED`.
11. **Temporal constraints** — no `ACTIVE` closure on the target area, a guest pass's `valid_on` equal to the current logical date, a new closure window overlapping nothing already `SCHEDULED` or `ACTIVE` on its area: `ERR_AREA_CLOSED`, `ERR_GUEST_PASS_NOT_REDEEMABLE`, `ERR_CLOSURE_OVERLAP`.
12. **Quotas, always last** — the area's `OPEN`-visit count below its effective capacity, and the sponsor's monthly guest-pass usage below its limit: `ERR_AREA_AT_CAPACITY`, `ERR_GUEST_PASS_MONTHLY_LIMIT`.

Ordering is observable behavior. A renewal carrying a stale `expected_membership_version` surfaces `ERR_STALE_VERSION` rather than any state error, and a check-in presenting an unverified dog at a full area surfaces `ERR_DOG_NOT_VERIFIED` rather than `ERR_AREA_AT_CAPACITY` — quota checks run only for otherwise-admissible requests.

### 2.8. Nested Resource Retrieval

Endpoints whose paths chain identifiers — a dog or membership beneath a member, a closure or waste station beneath an area — validate path identifiers from left to right: the parent identifier (`memberId`, or `areaId` where an area is the parent) first, then the child identifier. The request is rejected immediately with the 404 error corresponding to the first identifier that does not exist, and later identifiers are never consulted. The not-found family is `ERR_MEMBER_NOT_FOUND`, `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`. A request addressing a dog beneath a member who does not exist therefore surfaces `ERR_MEMBER_NOT_FOUND` before the dog is ever examined.

### 2.9. Money, Points, and Percentages: Precision and Rounding

All monetary values are integer cents. Where a fee is assembled from multiple lines, each line is rounded half-up to a whole cent first and the rounded lines are then summed; summing the raw lines and rounding once produces a different number and is not the contract. Strike scoring is integer points, with half-up rounding applied only to the pending-reports half-weight term (§3.7). Waste-station fill is an integer percentage capped at 100. Occupancy figures, monthly guest-pass usage, dog counts, and renewal tallies are integer counts.

### 2.10. Cascading Consistency and Atomic Side Effects

State changes in this system propagate immediately, and every side effect of an operation commits atomically within the triggering request — there are no deferred or eventually-consistent cascades. A confirmed incident that suspends a member also suspends their membership, force-closes their open visits, and voids their outstanding guest passes in the same request; a lapsed renewal reactivates its member in the same request; a nightly epoch applies all six of its stages in one atomic pass. Cascades recompute every derived field they touch — area occupancy, monthly guest-pass usage, strike scores — as part of that same request, and each mutated entity independently refreshes `updated_at` and increments `version`, so one suspension may advance the version of a member, a membership, several visits, and several passes at once.

## 3. Business Logic & Workflows

### 3.1. Enrollment: Member Registration, Profiles, and Steward Appointment

An `Anonymous` caller opens the door. Registration requires a `full_name` and an `email` — the address is unique per member, and registering or later updating into an email another member already carries is rejected with `ERR_INVALID_REQUEST` — with `phone` optional and defaulting to null (a non-string, non-null `phone` is likewise `ERR_INVALID_REQUEST`). The new Member is created in `PENDING_VERIFICATION` status with `strike_points` at 0, `provisional_strike_score` at 0, `guest_passes_used_this_month` at 0, `is_steward` false, and `version` 1. A registrant stays `PENDING_VERIFICATION` until the first membership purchase (§3.3) moves them to `ACTIVE`: the park does not consider a registration real until a verified dog and a paid term stand behind it.

Profile upkeep is light. A member — or an administrator on their behalf — updates `full_name`, `email`, or `phone` through the OCC-guarded profile capability (§2.6), which increments the member's `version` by one on success. Member-role callers may touch only their own record, with `ERR_NOT_OWNER` greeting any attempt on another's; reads of a member record follow the same self-only rule for the `Member` role, while `Steward` and `ParkAdmin` callers read freely.

Volunteer stewards are appointed, never self-declared. A `ParkAdmin` grants or revokes the privilege by setting `is_steward` on the member record, which increments `version` by one; the flag is precisely what authorizes `X-User-Role: Steward` on later requests (§2.1), so revoking it takes effect on the steward's very next call.

### 3.2. Dog Registration and Vaccination Verification

With an account in place, a member registers each dog under their own account — administrators may register on a member's behalf — by supplying the dog's `name`, a `size_class` of `SMALL` or `LARGE` that will later gate area admission, the municipal `license_number`, and the rabies `vaccination_expires_on` as an ISO date — a value that is not a well-formed `YYYY-MM-DD` calendar date is rejected with `ERR_INVALID_REQUEST` at registration and again at resubmission. The Dog is created with `verification_status` `SUBMITTED`, `rejection_reason` null, and `member_id` bound to the owning account. Dogs are readable by their owner and by stewards and administrators, and listing a member's dogs follows the same self-only rule for the `Member` role.

Document review sits on the administrator's desk. Verification of a `SUBMITTED` dog takes a `decision` of `VERIFIED` or `REJECTED`. Approving moves the dog `SUBMITTED → VERIFIED`, but only when its `vaccination_expires_on` is on or after the current logical date — an expired rabies certificate cannot be approved and is rejected with `ERR_VACCINATION_EXPIRED` (HTTP 422). Rejecting moves the dog `SUBMITTED → REJECTED` and records the request's `reason` — optional, a string or null — verbatim into `rejection_reason`; a `reason` sent alongside a `VERIFIED` decision is accepted but not stored. A verification attempt on a dog no longer in `SUBMITTED` is rejected with `ERR_DOG_NOT_VERIFIABLE`. Either outcome increments the dog's `version`.

Resubmission is the owner's path back into review. A dog in `REJECTED` or `EXPIRED` may be resubmitted by its owning member with refreshed `vaccination_expires_on` and `license_number`; the move `REJECTED → SUBMITTED` or `EXPIRED → SUBMITTED` clears `rejection_reason` to null and requires the new vaccination date to be on or after the current logical date, failing with `ERR_VACCINATION_EXPIRED` otherwise. Resubmission from any other status is rejected with `ERR_DOG_NOT_RESUBMITTABLE`, and a member resubmitting another member's dog hears `ERR_NOT_OWNER`.

Vaccination validity is a continuing obligation rather than a one-time gate: the nightly service-run sweeps any `VERIFIED` dog whose `vaccination_expires_on` has fallen before the run's date into `EXPIRED` (§3.8), and the gate re-verifies vaccination currency on every single entry (§3.5).

### 3.3. Membership Purchase, Proration, and Renewal

The first purchase turns a registrant into a member. Buying the initial annual membership requires at least one of the member's dogs to stand in `VERIFIED` status; without one the purchase is rejected with `ERR_NO_VERIFIED_DOG`. On success the Membership is created in `ACTIVE` status with `term_start` at the purchase instant and `term_end` pinned to the final instant of the calendar year — December 31 at 23:59:59 UTC — and the member flips `PENDING_VERIFICATION → ACTIVE` with the member's `version` incremented by one. `renewal_count` begins at 0. The purchase consults no member-status rule beyond the verified-dog gate: a member in any status may buy, each purchase mints a fresh `ACTIVE` membership with `renewal_count` 0, and only a `PENDING_VERIFICATION` purchaser changes status — an already-`ACTIVE`, `LAPSED`, or `SUSPENDED` purchaser keeps their current status alongside the new membership.

The fee, recorded as `charged_fee_cents`, is prorated to the remaining calendar. Count the whole days from the purchase date (inclusive) through December 31 (inclusive) — the days remaining. The base line is 12000 cents (a $120 annual fee) multiplied by the days remaining and divided by the 365 days of the year, rounded half-up to a whole cent. The per-dog line covers every verified dog beyond the first: take the count of the member's dogs in `VERIFIED` status at purchase time, subtract one, and floor the result at zero; multiply that count by 3000 cents ($30 per additional dog), then by the days remaining, divide by 365, and round half-up to a whole cent. `charged_fee_cents` is the sum of the two independently rounded lines — rounding happens per line before summation, never once on the total. A member lists their own memberships, with administrators sharing that access; there is no single-membership read endpoint.

Renewal keeps the term alive and comes in two flavors, both flowing through the same OCC-guarded renewal capability (§2.6), on which the version check fires first, before any member-state or membership-state evaluation:

- **Early renewal** applies when the membership is `ACTIVE` at renewal time. The member must be `ACTIVE` — evaluated before the membership's own state, with `ERR_MEMBER_NOT_ACTIVE` greeting any other member status. Each fee line takes a ten-percent early-bird discount: the base line is 12000 cents at nine-tenths, rounded half-up (10800 cents); the per-dog line is 3000 cents times the verified dogs beyond the first, at nine-tenths, rounded half-up; `charged_fee_cents` is the sum of the rounded lines. The term extends — `term_end` moves to December 31 of the year after the current `term_end` — making this transition a self-loop, `ACTIVE → ACTIVE`. Successive early renewals are legitimate, each pushing the term out one more year; the version guard is the only protection against an unobserved double extension.
- **Lapsed renewal** applies when the membership is `EXPIRED` at renewal time. The member must be `LAPSED` — again evaluated before the membership's state, with `ERR_MEMBER_NOT_ACTIVE` otherwise. The fee is the full, undiscounted calendar year with no proration: 12000 cents plus 3000 cents for each verified dog beyond the first, plus a flat 2500-cent reinstatement fee. `term_start` restarts at the renewal instant and `term_end` lands on December 31 of the current year. The same request cascades the member `LAPSED → ACTIVE`.

Both flavors increment `renewal_count` by one and the membership's `version` by one, and record the freshly computed `charged_fee_cents`. For both flavors, the per-dog line takes the count of the member's dogs in `VERIFIED` status at renewal time. A membership in any other status has no renewal path, and an attempt to renew one is rejected with `ERR_MEMBER_NOT_ACTIVE`.

### 3.4. Park Areas, Peak Windows, and Maintenance Closures

Administrators shape the park as a set of areas. Creating an area takes a `name`, a `size_class_restriction` of `SMALL` or `LARGE` (only matching dogs and guest passes are ever admitted), a standard `capacity` — the maximum number of concurrent `OPEN` visits, an integer strictly greater than zero — a `peak_capacity` for busy windows, an integer between 0 and `capacity` inclusive, and optionally `peak_windows`, a list of minute-of-day ranges each described by a `start_minute` and an `end_minute` and interpreted half-open: the window includes its start minute and excludes its end minute. Each window's minutes must be integers with 0 ≤ `start_minute` < `end_minute` ≤ 1440, failing which the create is rejected with `ERR_INVALID_REQUEST`. When omitted — or explicitly null — `peak_windows` defaults to an empty list. A freshly created area reports `current_occupancy` 0 and an `effective_capacity` equal to its `capacity`. Areas and their closures are readable by every authenticated role.

Effective capacity is a live computation, exposed on every area read and consulted at the gate. If any closure on the area stands `ACTIVE`, `effective_capacity` is zero. Otherwise, when the current logical minute-of-day falls inside any peak window, it is the lesser of `capacity` and `peak_capacity`. At all other times it is simply `capacity`. The companion figure `current_occupancy` counts exactly the area's visits in `OPEN` status — `CLOSED` and `FORCE_CLOSED` visits never count — and is recomputed on every check-in, check-out, and force-close.

Maintenance takes areas offline through closure windows. Scheduling a closure on an area requires `starts_at` and `ends_at` as full UTC instants — `ends_at` strictly after `starts_at`, or `ERR_INVALID_REQUEST` — plus a `reason`, and the window is half-open: it covers its start instant and stops at its end instant. A new window must not overlap any existing `SCHEDULED` or `ACTIVE` closure on the same area; adjacency is allowed, so a window beginning exactly when another ends is acceptable, while genuine overlap is rejected with `ERR_CLOSURE_OVERLAP`. The window is never compared against the current logical time at scheduling, so a window lying entirely in the past is accepted; because activation requires the run time to precede `ends_at`, such a window never activates and simply remains `SCHEDULED`. A closure begins life `SCHEDULED`; the nightly run flips it `SCHEDULED → ACTIVE` once the logical time has reached `starts_at` while still preceding `ends_at`, and `ACTIVE → COMPLETED` once the logical time reaches or passes `ends_at`. An administrator may also cancel a closure, but only while it remains `SCHEDULED` — `SCHEDULED → CANCELLED` — with any other status earning `ERR_CLOSURE_NOT_CANCELLABLE`; `COMPLETED` and `CANCELLED` are terminal. While a closure stands `ACTIVE`, every check-in to its area is rejected with `ERR_AREA_CLOSED` (§3.5).

### 3.5. Gate Operations: Check-in, Check-out, and Occupancy

Check-in admits one animal per request: the payload carries an `area_id` plus exactly one of `dog_id` for a member's own dog or `guest_pass_id` for a sponsored guest — supplying both or neither is `ERR_INVALID_REQUEST`. The created ParkVisit opens in `OPEN` status with `checked_in_at` stamped at the current logical instant, `checked_out_at` null, `close_reason` null, and `member_id` bound to the caller — which for a guest visit is the pass's sponsor, and which for any check-in performed by a `ParkAdmin`, whose own identity is opaque, is the dog's owning member or the pass's sponsor rather than the administrator.

The gate evaluates the full adjudication pipeline of §2.7, with the business stages specialized per visit kind. For a dog visit, the dog must belong to the caller (`ERR_NOT_OWNER`; administrators are exempt), must stand `VERIFIED` (`ERR_DOG_NOT_VERIFIED`), and its `vaccination_expires_on` must be on or after the current logical date (`ERR_VACCINATION_EXPIRED`). For a guest visit, the pass must be `ISSUED` and its `valid_on` must equal the current logical date — any other status or date is `ERR_GUEST_PASS_NOT_REDEEMABLE` — and redemption flips the pass `ISSUED → REDEEMED` within the same request. Size discipline applies to both kinds: the dog's `size_class` or the pass's `guest_dog_size_class` must equal the area's `size_class_restriction`, or `ERR_DOG_SIZE_AREA_MISMATCH`. No dog may hold two open visits at once — a dog with an `OPEN` visit anywhere is turned away with `ERR_ALREADY_CHECKED_IN`, however long ago that visit began. An area under an `ACTIVE` closure rejects with `ERR_AREA_CLOSED`. Finally, last in the pipeline, the capacity quota: the check-in proceeds only while the area's `OPEN`-visit count is strictly below its `effective_capacity`; occupancy equal to the effective capacity rejects with `ERR_AREA_AT_CAPACITY`, while occupancy one below still admits. A successful entry recomputes the area's `current_occupancy`.

Departure is voluntary check-out: the visit's owning member — or an administrator — closes an `OPEN` visit, moving it `OPEN → CLOSED` with `checked_out_at` stamped and `close_reason` set to `VOLUNTARY`. Closing a visit that is not `OPEN` is rejected with `ERR_VISIT_NOT_OPEN`, and a member attempting to close another member's visit hears `ERR_NOT_OWNER`. Involuntary departure, `OPEN → FORCE_CLOSED`, arrives only through the two system paths: a member suspension with `close_reason` `MEMBER_SUSPENDED` (§3.7) and the nightly sweep with `close_reason` `NIGHTLY_SWEEP` (§3.8); both stamp `checked_out_at` and recompute occupancy. Visits are listable by stewards and administrators with optional filters on `member_id`, `dog_id`, `area_id`, `guest_pass_id`, and `status`, while individual visits are also readable by their own member.

### 3.6. Guest Passes and the Monthly Allotment

An `ACTIVE` member sponsors guests by purchasing day passes, supplying the guest dog's `guest_dog_size_class` (`SMALL` or `LARGE`) and a `valid_on` date that may lie in the future — nothing ties `valid_on` to the current logical date at purchase, so past, present, and future dates are all accepted and only a malformed date earns `ERR_INVALID_REQUEST`; redeemability is judged solely at the gate. The sponsor is taken from the caller's identity into `sponsor_member_id` — a caller whose `X-User-ID` matches no persisted member is rejected with `ERR_MEMBER_NOT_FOUND` — and only members in `ACTIVE` status may purchase: any other member status is rejected with `ERR_MEMBER_NOT_ACTIVE`. The pass is created `ISSUED`.

Pricing keys off the visit day rather than the purchase day. A `valid_on` falling on a Saturday or Sunday — judged in UTC — prices at the weekday base of 1500 cents multiplied by one-and-a-half and rounded half-up: 2250 cents. A `valid_on` falling Monday through Friday prices at the flat 1500 cents. The result is recorded on the pass as `fee_cents`.

Each member holds a limited guest allotment: at most two passes per calendar month. The usage figure, exposed as `guest_passes_used_this_month`, counts the sponsor's passes created within the current calendar month of the logical clock whose status is `ISSUED`, `REDEEMED`, or `EXPIRED` — `VOID` passes are excluded, so voiding genuinely refunds the allotment. A purchase attempted while the count stands at two is rejected with `ERR_GUEST_PASS_MONTHLY_LIMIT`; a count of one still admits.

Passes die three deaths. Redemption at the gate moves `ISSUED → REDEEMED` (§3.5). An administrator may void a pass — `ISSUED → VOID` — but only while it remains `ISSUED`; attempting to void a `REDEEMED`, `EXPIRED`, or already-`VOID` pass is rejected with `ERR_GUEST_PASS_NOT_VOIDABLE`, and a successful void recomputes the sponsor's monthly usage with the voided pass excluded. The nightly run expires any pass whose `valid_on` has fallen before the run's date, `ISSUED → EXPIRED`, and an expired pass still counts against its purchase month's allotment. A sponsor's suspension voids every outstanding `ISSUED` pass as part of the cascade (§3.7), refunding the allotment in the process. Members list and read only their own passes — a list's `sponsor_member_id` filter must equal the caller or is auto-scoped to it — while stewards and administrators see all passes, with optional `status` and `valid_on` filters.

### 3.7. Incident Reports, Strike Scoring, and Suspension

When a bite or aggression event occurs, any member, steward, or administrator may file a report. The payload names the `subject_member_id` the report is against, a `severity` of `MINOR`, `MAJOR`, or `SEVERE`, the free-text `description`, and the `occurred_at` instant; an involved `subject_dog_id` and the `area_id` where it happened are optional. Nobody may report themselves: a `subject_member_id` equal to the reporting member's own id is rejected with `ERR_SELF_REPORT_NOT_ALLOWED` (HTTP 422). The report is created in `FILED` status with `reporter_member_id` taken from the caller's identity — or null when an administrator files. Filing immediately recomputes the subject's `provisional_strike_score`, because a `FILED` report already counts at half weight.

Scoring separates the proven from the pending. A subject's `strike_points` — the authoritative figure that drives suspension — is a running total that accrues severity points as reports reach `CONFIRMED`, and only then: ten points for `MINOR`, twenty for `MAJOR`, thirty for `SEVERE`, each report contributing exactly once at its own confirmation. Because reinstatement zeroes the running total, reports confirmed before a reinstatement do not re-enter it afterwards. The advisory `provisional_strike_score` starts from the same confirmed total and adds half the severity points of the reports still pending (`FILED` or `UNDER_REVIEW`), with that half-weight term rounded half-up to a whole point. `DISMISSED` reports count toward neither figure.

Triage and adjudication are deliberate and role-split. Advancing a report takes its target in the `to` field, which admits exactly `UNDER_REVIEW`, `CONFIRMED`, and `DISMISSED` — any other value is `ERR_INVALID_REQUEST`. From `FILED` the only move is `FILED → UNDER_REVIEW`, open to stewards — members whose `is_steward` flag is set — and to administrators, and it recomputes the subject's provisional score; because `FILED` and `UNDER_REVIEW` both count at half weight, that recompute never changes the value, the subject's member record is not mutated on this move, and a `resolution_note` supplied with it is accepted but not recorded. From `UNDER_REVIEW`, an administrator and only an administrator may move the report `UNDER_REVIEW → CONFIRMED` or `UNDER_REVIEW → DISMISSED`; a steward attempting either outcome receives `ERR_INSUFFICIENT_PERMISSIONS` — an authorization-stage rejection that fires before the report's existence or state is ever examined. Any advance whose target is not reachable from the report's current status — including anything out of the terminal `CONFIRMED` or `DISMISSED` states — is rejected with `ERR_INCIDENT_NOT_ADVANCABLE`. Both terminal outcomes record an optional `resolution_note` when one is provided, and a dismissal recomputes the subject's provisional score with the report no longer pending.

Confirmation is the park's enforcement hammer. When a report becomes `CONFIRMED`, the subject's `strike_points` is recomputed at full weight, and if the total reaches at least thirty — exactly thirty included — the member is suspended within the same request, provided the member stands `ACTIVE` at that moment; a `LAPSED` or already-`SUSPENDED` subject accrues the points but no suspension cascade runs. The suspension flips the member `ACTIVE → SUSPENDED`; flips every `ACTIVE` membership of theirs to `SUSPENDED`; force-closes every `OPEN` visit of theirs with `close_reason` `MEMBER_SUSPENDED`, stamping `checked_out_at` and recomputing each affected area's `current_occupancy`; and flips every `ISSUED` guest pass they sponsored to `VOID`, recomputing `guest_passes_used_this_month` with the voided passes excluded so the allotment is refunded. All of it commits atomically (§2.10), and every mutated entity's `version` advances by one.

Reinstatement is an administrator's call, available only for a `SUSPENDED` member — any other status is `ERR_MEMBER_NOT_SUSPENDED` — and it always resets `strike_points` to zero. Where the member lands depends on the member's most recently created membership: if that membership stands `SUSPENDED`, the member returns `SUSPENDED → ACTIVE` and the membership rides along `SUSPENDED → ACTIVE`; if that membership has already run to `EXPIRED`, the member instead lands `SUSPENDED → LAPSED` — strikes cleared, membership still expired — and the road back to `ACTIVE` is the lapsed renewal of §3.3; and a member with no membership at all, or whose latest membership stands in any other status, returns to `ACTIVE` with no membership mutated. Reports and their outcomes are visible to stewards and administrators, listable with filters on `reporter_member_id`, `subject_member_id`, `subject_dog_id`, `area_id`, and `status`.

### 3.8. Waste Stations and the Nightly Service Run

Park hygiene is metered through waste stations. An administrator installs a station into an area with just a `name`; it begins with `fill_pct` at 0, status `OK`, and `last_serviced_at` null until its first servicing. Stewards and administrators list the stations of an area.

Usage accrues nightly rather than per visit. On each service run, every station gains twenty-five percentage points for each visit checked into its area since the previous run — or since the station's creation when no run has yet occurred — counting visits of every status, with the accumulated `fill_pct` capped at 100. A station whose total reaches at least eighty flips `OK → NEEDS_SERVICE`; at seventy-five (three fresh visits) it stays `OK`, while a fourth visit pushes it to 100 and trips the flag. Servicing, recorded by a steward or an administrator, returns the station from either `OK` or `NEEDS_SERVICE` to `OK`, zeroes `fill_pct`, and stamps `last_serviced_at` with the current logical time.

The nightly service run itself is an administrator-triggered epoch executing six cascades atomically, in this pinned order:

1. Force-close every `OPEN` visit with `close_reason` `NIGHTLY_SWEEP`, stamping `checked_out_at` and recomputing each affected area's occupancy.
2. Expire memberships whose `term_end` is before the run's logical time — `ACTIVE → EXPIRED` or `SUSPENDED → EXPIRED`; where the prior status was `ACTIVE`, the owning member lapses `ACTIVE → LAPSED` in the same run, while a `SUSPENDED` member remains suspended. A member already non-`ACTIVE` for any other reason — say `LAPSED` behind a freshly purchased `ACTIVE` membership — is left untouched.
3. Expire `ISSUED` guest passes whose `valid_on` is before the run's date, recomputing each sponsor's monthly usage with the expired passes still counting.
4. Advance closure windows: `SCHEDULED → ACTIVE` where the run time has reached `starts_at` but not yet `ends_at`, and `ACTIVE → COMPLETED` where the run time has reached or passed `ends_at`.
5. Accumulate waste-station fill as described above and flag `NEEDS_SERVICE` where the threshold is met.
6. Sweep `VERIFIED` dogs whose `vaccination_expires_on` is before the run's date into `EXPIRED`.

Every entity mutated anywhere in the epoch has its `version` incremented and `updated_at` refreshed. The run's response reports the epoch's yield as integer tallies: `visits_force_closed`, `memberships_expired`, `members_lapsed`, `guest_passes_expired`, `closures_activated`, `closures_completed`, `dogs_expired`, and `stations_flagged`.

## 4. Endpoint Definitions

Operations that create a new resource — a member, a dog, a membership, a guest pass, an area, a closure, a visit at check-in, an incident report, or a waste station — return `201 Created`. Operations that modify an existing resource return `200 OK`. The nightly service-run epoch responds with `201 Created` carrying its tally payload, and the logical-clock capability responds with `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dog-park/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | ParkAdmin |
| POST | `/dog-park/members` | Register a new member account | Anonymous |
| GET | `/dog-park/members/{memberId}` | Get a member (Member role: self only) | Member, Steward, ParkAdmin |
| PATCH | `/dog-park/members/{memberId}` | Update a member profile with OCC on Member.version | Member, ParkAdmin |
| POST | `/dog-park/members/{memberId}/reinstate` | Reinstate a suspended member; clears strikes and reactivates a SUSPENDED membership | ParkAdmin |
| POST | `/dog-park/members/{memberId}/steward-status` | Grant or revoke the volunteer-steward flag | ParkAdmin |
| POST | `/dog-park/members/{id}/dogs` | Register a dog for a member (vaccination and license submitted for verification) | Member, ParkAdmin |
| GET | `/dog-park/members/{id}/dogs` | List a member's dogs (Member role: self only) | Member, Steward, ParkAdmin |
| GET | `/dog-park/dogs/{dogId}` | Get a dog (Member role: owner only) | Member, Steward, ParkAdmin |
| POST | `/dog-park/dogs/{dogId}/verify` | Verify or reject a submitted dog's vaccination and license documents | ParkAdmin |
| POST | `/dog-park/dogs/{dogId}/resubmit` | Resubmit a REJECTED or EXPIRED dog with refreshed vaccination and license data | Member |
| POST | `/dog-park/members/{id}/memberships` | Purchase the initial annual membership (prorated fee; term ends December 31) | Member, ParkAdmin |
| GET | `/dog-park/members/{id}/memberships` | List a member's memberships (Member role: self only) | Member, ParkAdmin |
| POST | `/dog-park/memberships/{membershipId}/renew` | Renew a membership with OCC: early renewal (ACTIVE, 10% off, extends a year) or lapsed renewal (EXPIRED, full fee plus reinstatement) | Member, ParkAdmin |
| POST | `/dog-park/guest-passes` | Purchase a guest day pass (sponsor is the calling member) | Member |
| GET | `/dog-park/guest-passes` | List guest passes, filterable (Member role: scoped to own sponsorship) | Member, Steward, ParkAdmin |
| GET | `/dog-park/guest-passes/{passId}` | Get a guest pass (Member role: sponsor only) | Member, Steward, ParkAdmin |
| POST | `/dog-park/guest-passes/{passId}/void` | Void an ISSUED guest pass (refunds the sponsor's monthly allotment) | ParkAdmin |
| POST | `/dog-park/areas` | Create a park area (size-class restriction, capacity, peak derating) | ParkAdmin |
| GET | `/dog-park/areas` | List park areas with computed occupancy and effective capacity | Member, Steward, ParkAdmin |
| GET | `/dog-park/areas/{areaId}` | Get a park area with computed current_occupancy and effective_capacity | Member, Steward, ParkAdmin |
| POST | `/dog-park/areas/{id}/closures` | Schedule a maintenance closure window (half-open; no overlap with SCHEDULED/ACTIVE closures on the same area) | ParkAdmin |
| GET | `/dog-park/areas/{id}/closures` | List closure windows for an area | Member, Steward, ParkAdmin |
| POST | `/dog-park/closures/{closureId}/cancel` | Cancel a SCHEDULED closure | ParkAdmin |
| POST | `/dog-park/visits/check-in` | Gate check-in with a member dog or a guest pass (exactly one); enforces verification, vaccination, size rule, closure, and capacity | Member, ParkAdmin |
| POST | `/dog-park/visits/{visitId}/check-out` | Voluntary check-out of an OPEN visit | Member, ParkAdmin |
| GET | `/dog-park/visits` | List visits, filterable by all foreign keys and status | Steward, ParkAdmin |
| GET | `/dog-park/visits/{visitId}` | Get a visit (Member role: own visits only) | Member, Steward, ParkAdmin |
| POST | `/dog-park/incident-reports` | File a bite or aggression incident report against a member | Member, Steward, ParkAdmin |
| GET | `/dog-park/incident-reports` | List incident reports, filterable | Steward, ParkAdmin |
| GET | `/dog-park/incident-reports/{reportId}` | Get an incident report | Steward, ParkAdmin |
| POST | `/dog-park/incident-reports/{reportId}/advance` | Advance a report: FILED to UNDER_REVIEW (Steward or ParkAdmin); UNDER_REVIEW to CONFIRMED or DISMISSED (ParkAdmin only) | Steward, ParkAdmin |
| POST | `/dog-park/areas/{id}/waste-stations` | Install a waste station in an area | ParkAdmin |
| GET | `/dog-park/areas/{id}/waste-stations` | List waste stations in an area | Steward, ParkAdmin |
| POST | `/dog-park/waste-stations/{stationId}/service` | Record waste-station servicing (empties the station, clears NEEDS_SERVICE) | Steward, ParkAdmin |
| POST | `/dog-park/service-runs/nightly` | Execute the nightly service-run epoch: six pinned cascades, atomically | ParkAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue fixes only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_A_STEWARD` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_DOG_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_GUEST_PASS_NOT_FOUND` | 404 Not Found |
| `ERR_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSURE_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_WASTE_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEMBER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_DOG_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_DOG_NOT_RESUBMITTABLE` | 409 Conflict |
| `ERR_DOG_NOT_VERIFIED` | 409 Conflict |
| `ERR_NO_VERIFIED_DOG` | 409 Conflict |
| `ERR_GUEST_PASS_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_GUEST_PASS_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CLOSURE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_VISIT_NOT_OPEN` | 409 Conflict |
| `ERR_INCIDENT_NOT_ADVANCABLE` | 409 Conflict |
| `ERR_DOG_SIZE_AREA_MISMATCH` | 409 Conflict |
| `ERR_ALREADY_CHECKED_IN` | 409 Conflict |
| `ERR_CLOSURE_OVERLAP` | 409 Conflict |
| `ERR_AREA_CLOSED` | 409 Conflict |
| `ERR_AREA_AT_CAPACITY` | 409 Conflict |
| `ERR_GUEST_PASS_MONTHLY_LIMIT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VACCINATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SELF_REPORT_NOT_ALLOWED` | 422 Unprocessable Entity |
