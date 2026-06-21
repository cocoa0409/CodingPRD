# Jury Duty Management API — Product Requirements Document

## 1. Introduction

The Jury Duty Management API coordinates the full administrative arc of empaneling citizens for jury service, from the moment a court assembles its qualified pool to the final accounting of each juror's pay and mileage. A jurisdiction runs its calendar in discrete **service terms**; each term owns a pool of prospective jurors, a statutory pay configuration, and a running tally of how many people have been summoned and how many remain eligible to be drawn. Around that aggregate, the system orchestrates summons issuance, the qualification questionnaire, the deferral/excusal/exemption process, daily check-in and reporting, panel assignment for individual trials, and the disciplinary handling of jurors who fail to appear.

The system is built for four cooperating offices whose responsibilities barely overlap: a jury administrator who seeds and runs the pool, a court clerk who shepherds each summons through reporting and pay, a judge who readies trials and empanels juries, and the summoned juror who answers their own summons. Because two clerks can legitimately work the same panel and two draws can legitimately consume the same pool, the design leans on explicit version checks and a deterministic, auditable selection order rather than wall-clock timing. The remainder of this document fixes the global contracts every endpoint shares, then walks the business workflows in narrative form, and finally tabulates the endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `JuryAdministrator`, `CourtClerk`, `Judge`, and `Juror`. If either header is absent, or if `X-User-Role` is not one of these four declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three administrative roles — `JuryAdministrator`, `CourtClerk`, and `Judge` — are operator roles. When `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for an actor stamp (for example, the `decided_by_role` field on a disposition records the deciding actor's role) but it never compares the operator's `X-User-ID` to any entity's `id`. By contrast, when `X-User-Role` is `Juror`, `X-User-ID` is the `id` of the acting `Juror`. Ownership checks on any resource that references a `Juror` compare the resource's foreign-key field to `X-User-ID`: specifically, a juror submitting a qualification questionnaire or requesting a disposition on a summons must own that summons, meaning the summons's `juror_id` must equal `X-User-ID`; otherwise the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

Every list endpoint is paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of records to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order, so the oldest record appears first.

Each list response surfaces four pagination fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`. The `total_count` reflects the full size of the filtered collection before pagination is applied, and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Identity

Most resources in the system are mutable aggregates and carry a standard quartet of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created, and `updated_at` is an ISO 8601 UTC timestamp refreshed on every subsequent modification. The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it underpins the optimistic concurrency mechanism described in §2.6. The mutable aggregates that carry all four fields are the service term, juror, summons, disposition, trial, panel, panel assignment, and pay voucher.

Three record types are append-only audit rows and are deliberately leaner: a **qualification response**, a **check-in**, and a **strike** each carry only `id` and `created_at`. For these three, both `updated_at` and `version` are absent, because once written they are never mutated.

### 2.5. Hierarchical Consistency and Automatic Reconciliation

The system maintains immediate consistency across its resource hierarchy. Many operations mutate more than one entity, and every such cascade is part of the operation's contract rather than an optional side effect. When the server adjusts a resource as the downstream consequence of another operation — for example, recomputing a term's pool size, flipping a juror to disqualified, or reverting a summons when its seat is freed — that adjustment is itself a mutation: it refreshes the affected resource's `updated_at` and increments its `version`. Counters that the scaffold marks as computed (`pool_size`, `summoned_count`, `seated_count`, `service_days`, `deferral_count`, `fta_strike_count`) are always recomputed from their underlying rows so they faithfully reflect current state.

For any request whose URL names nested resources, identifiers are validated left to right against the live data. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in the path — or the first body-referenced identifier — that does not resolve to an existing resource. A check-in posted against a summons that does not exist, for instance, fails on the summons lookup before any check-in rule is evaluated.

### 2.6. Optimistic Concurrency Control

Two operations in this system require the client to prove it is acting on a current view of a shared parent, because both legitimately consume a shared resource and the product allows independent operators to target the same parent.

A request to draw jurors from a service term must include `expected_service_term_version`, carrying the client's last observed `version` of that `ServiceTerm`. A draw consumes qualified jurors from the shared pool and increments the term's `version` by one; therefore, if `expected_service_term_version` does not equal the term's current `version`, the draw is rejected with `ERR_STALE_TERM_VERSION` (HTTP 412). This prevents a second draw that still carries the version observed before an earlier draw landed from working off a stale pool snapshot and double-drawing the same juror.

A request to seat a summons into a panel must include `expected_panel_version`, carrying the client's last observed `version` of that `Panel`. Seating increments the panel's `version` by one; if `expected_panel_version` does not equal the panel's current `version`, the seat request is rejected with `ERR_STALE_PANEL_VERSION` (HTTP 412). Because any reporting juror may take any open seat on a forming panel, a sequential second seat that still carries the version observed before the first seat landed is operating on a stale view of the panel's remaining seats and must fail. Both `expected_service_term_version` and `expected_panel_version` are non-optional inputs on their respective operations; no other endpoint takes a version field.

### 2.7. Monetary Values, Counts, and Rounding Discipline

All monetary amounts in the system — the term's `daily_pay_cents`, `half_day_pay_cents`, and `mileage_rate_cents` configuration, and the computed `attendance_cents`, `mileage_cents`, and `total_cents` on a pay voucher, along with the projected exposure figure — are integer cents. Counts such as `paid_days`, `service_days`, `seated_count`, and the strike count are integers.

Rounding discipline is precise and, importantly, differs by calculation. Wherever a monetary figure must be rounded, the half-up method is used (a value exactly at the halfway point rounds away from zero to the next whole cent). The **order** in which rounding is applied relative to summation is pinned per calculation and is described with each formula in §3; the two mileage calculations in this system round in deliberately opposite orders, and an implementation must honor each one exactly as written rather than assuming a single uniform policy.

### 2.8. The Server Clock and Temporal Gates

Several rules in this system compare against "now" — most notably the report-date gates on check-in and failure-to-appear, and the current-year input to the age check in qualification. The system reads the current instant from a server-managed logical clock rather than the host wall clock, so that temporal behavior is reproducible. An administrative test-driving capability lets a `JuryAdministrator` set this clock to a supplied instant via the `to_iso8601` field; the response echoes the new `current_utc`. The current calendar year used in the age calculation is the year of this server clock.

## 3. Business Logic & Workflows

### 3.1. Establishing a Service Term and Its Pool

The organizing aggregate of the system is the **service term**, created by a `JuryAdministrator`. At creation the administrator supplies a `name` (a human label such as a quarter and panel type), a `report_date` (the ISO 8601 UTC date on which summoned jurors must report), and the term's pay configuration: `daily_pay_cents` for a full service day, `half_day_pay_cents` for a half day, the `full_day_hours` threshold that separates the two, `mileage_rate_cents` reimbursed per mile, and `pay_day_cap`, the maximum number of paid service days reimbursed for any one summons. The pay amounts and mileage rate must each be zero or greater, `full_day_hours` must be strictly greater than zero, and `pay_day_cap` must be at least one. The administrator may also supply `fta_disqualify_threshold`, the recorded failure-to-appear strike count at or above which a juror is automatically disqualified; when omitted it defaults to 3, and any supplied value must be at least one. A term is born in `DRAFT` status, which is its `status`. Two computed counters travel with the term: `pool_size`, the number of jurors in this term whose `qualification_status` is `QUALIFIED` and whose `disqualified` flag is false, and `summoned_count`, the number of summonses in the term that are not in a terminal cancelled state. A monotone `draw_seq` counter, starting at zero, advances on every draw and serves as the stable selection-order audit handle.

Before any summons may issue, the administrator seeds the pool by adding jurors to the term. Each juror is created with a `full_name`, a `birth_year` (which must fall within the years 1900 through 2010 inclusive), and `round_trip_miles` (the round-trip distance from residence to courthouse, which must be zero or greater and feeds mileage reimbursement). A new juror records its parent term in `service_term_id`, begins with `qualification_status` of `PENDING`, a `fta_strike_count` of 0, a `disqualified` flag of false, and a `last_drawn_seq` of 0 (which marks a juror that has never been drawn). A juror's qualification can be settled two ways: through the questionnaire described in §3.3, or by an administrative override that promotes a juror directly from `PENDING` to `QUALIFIED`. The override is only permitted while the juror's `disqualified` flag is false, and on success the term's `pool_size` is recomputed upward.

Opening the term advances its `status` from `DRAFT` to `OPEN`, an action reserved to the `JuryAdministrator`. The term may only be opened while it is in `DRAFT`, and only once at least one juror in the term is `QUALIFIED` with `disqualified` false; opening signals that summonses may now be drawn and issued. Closing the term advances it from `OPEN` to `CLOSED`, a terminal state that locks the term against any further draw, summons issuance, or check-in. A term may be closed only while it is `OPEN`, only when no summons in the term remains in `REPORTING` or `SERVING` (every reporting juror must have been released or dispositioned), and only when no panel in the term is still `FORMING`. Any attempt to draw, issue summonses, check in, or seat while the term is not `OPEN` is rejected with `ERR_TERM_NOT_OPEN` (HTTP 409), and a transition requested from a state in which it is not defined yields `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Drawing Jurors and Issuing Summonses

When a term is `OPEN`, the `JuryAdministrator` draws a batch of prospective jurors from the qualified pool. The draw request names a `count` of jurors to pull and carries `expected_service_term_version` for the concurrency check described in §2.6. Selection is **deterministic and auditable** — the server never picks by random identifier. The eligible set comprises jurors of the term whose `qualification_status` is `QUALIFIED`, whose `disqualified` flag is false, and who do not already hold a non-cancelled summons in this term. From that set the server ranks candidates by a "least-recently-burdened first" key, ascending on three levels in order: first by `last_drawn_seq` ascending, so never-drawn jurors (whose `last_drawn_seq` is 0) come first; then, among ties, by `fta_strike_count` ascending, preferring cleaner records; and finally, as the stable terminal tie-break, by `created_at` ascending — never by `id`. The server takes the first `count` jurors by this key.

If the eligible pool holds fewer than `count` jurors, the draw is rejected with `ERR_POOL_EXHAUSTED` (HTTP 409) and no summons is created. On success, the term's `draw_seq` increments by one, each drawn juror's `last_drawn_seq` is set to that new `draw_seq`, the term's `version` increments by one, and one summons in `SUMMONED` status is created for each drawn juror. The same constraint that excludes already-summoned jurors from the eligible set also guards the batch directly: a draw that would issue a second non-cancelled summons to a juror already summoned this term is rejected with `ERR_DUPLICATE_SUMMONS` (HTTP 409). Each new summons records its `service_term_id`, the `juror_id` of the drawn juror, and a `badge_number` — a monotone per-term sequence minted at issuance that serves as the stable check-in ordering handle. A fresh summons starts with `deferral_count` of 0, `service_days` of 0, and a null `deferred_to_term_id`.

The administrator can also gauge the term's financial exposure before committing through a what-if **pool projection**. This read-only capability computes the maximum mileage the term would owe if every qualified, non-disqualified juror reported for the full `pay_day_cap`. Its rounding order is pinned the opposite way from the per-voucher pay calculation, precisely to make the order-sensitivity observable: the server first sums the raw `round_trip_miles` across the eligible pool (the same set of jurors that count toward `pool_size`), multiplies that pooled mileage total by `pay_day_cap`, multiplies the result by `mileage_rate_cents`, and only then rounds the single product half-up to whole cents. The response reports this `projected_mileage_cents` alongside the current `pool_size`. A single terminal rounding — sum first, round once at the very end — is the rule here.

### 3.3. Qualification of the Summoned Juror

Once summoned, a juror answers a one-time qualification questionnaire on their own summons; this is the only path that moves a summons out of `SUMMONED`. The submission supplies four boolean affirmations: `is_citizen` (U.S. citizenship), `is_resident` (residency in the court's jurisdiction), `felony_conviction` (an unrestored-rights felony conviction), and `english_proficient` (sufficient English). Submitting the questionnaire creates a **qualification response**, which records its parent `summons_id` and a computed `evaluated_status`. Exactly one qualification response may exist per summons, and the summons must be in `SUMMONED` when it is submitted; a second submission or one against a summons past `SUMMONED` is an invalid-state condition (`ERR_INVALID_STATE`, HTTP 409).

The qualification verdict is a strict boolean predicate over the four answers plus the juror's age. The juror's age is the current calendar year (taken from the server clock) minus the juror's `birth_year`. The juror qualifies only when all of the following hold together: `is_citizen` is true, `is_resident` is true, `english_proficient` is true, `felony_conviction` is false, and the computed age is at least 18. If every one of these holds, `evaluated_status` is `QUALIFIED`; if any fails, `evaluated_status` is `INELIGIBLE`. There is no partial credit and no rounding — age is a whole-number difference of years.

The verdict branches the summons. When the response evaluates to `QUALIFIED`, the juror's `qualification_status` is set to `QUALIFIED`, the term's `pool_size` is recomputed, and the summons advances from `SUMMONED` to `QUALIFIED_PENDING`, awaiting the report date. When the response evaluates to `INELIGIBLE`, the juror's `qualification_status` is set to `INELIGIBLE` and the summons short-circuits directly to the terminal `EXCUSED` state, the excusal reason being ineligibility itself. The administrative override mentioned in §3.1 is the parallel path: it likewise lifts a juror from `PENDING` to `QUALIFIED` and recomputes `pool_size`, but it is permitted only while the juror is not `disqualified`. A juror who is `QUALIFIED` can later be driven to `INELIGIBLE` by the system when their `disqualified` flag flips true — that path is governed entirely by the failure-to-appear logic in §3.6.

### 3.4. Reporting, Check-In, and the Service Day

A `CourtClerk` records each day a juror physically reports by posting a check-in against the summons. The first check-in advances the summons from `QUALIFIED_PENDING` to `REPORTING`; every subsequent check-in keeps the summons in `REPORTING`. A check-in supplies a `service_date` (the ISO 8601 UTC calendar date of the service day) and `on_floor_hours` (the hours the juror was present on the floor that day, which must be zero or greater). Each check-in creates an append-only record recording its parent `summons_id`, and the summons's `service_days` counter increments by one with every check-in.

Check-in is gated on three conditions, each with its own rejection. The term must be `OPEN`, or the request fails with `ERR_TERM_NOT_OPEN` (HTTP 409). The `service_date` must be on or after the term's `report_date` — this is a closed lower bound, so a check-in dated exactly on the report date is allowed and one dated even a day earlier is rejected with `ERR_BEFORE_REPORT_DATE` (HTTP 409). And no existing check-in on the same summons may already share that `service_date`; a duplicate calendar date on one summons is rejected with `ERR_DUPLICATE_SERVICE_DATE` (HTTP 409), so no day is ever double-credited. The summons must also be in a state from which check-in is defined — `QUALIFIED_PENDING` for the first, `REPORTING` thereafter — or the attempt yields `ERR_INVALID_STATE` (HTTP 409).

Each check-in is classified into a `day_kind` at the moment it is recorded. When `on_floor_hours` is at or above the term's `full_day_hours`, the day is a `FULL` day; otherwise it is a `HALF` day. This classification, fixed per check-in, is what later distinguishes full-day pay from half-day pay when a voucher is computed.

### 3.5. Deferral, Excusal, and Exemption

Between qualification and reporting, a juror may ask to be relieved of service through a **disposition**. The juror requests one on their own summons, supplying a `kind` — one of `DEFER`, `EXCUSE`, or `EXEMPT` — and a `reason_code` drawn from `MEDICAL`, `HARDSHIP`, `STUDENT`, `AGE`, `PRIOR_SERVICE`, `MILITARY`, `CAREGIVER`, or `OTHER`. A `DEFER` request also names a `requested_term_id`, the later term the juror wishes to be moved to; this field is required for a deferral and is null for an excusal or exemption. The disposition records its `summons_id`, begins with a `decision` of `PENDING`, and leaves `decided_by_role` null until decided.

Deciding a disposition supplies a `decision` of either `GRANTED` or `DENIED`, and the decision is split by kind across two offices. A `DEFER` may be decided only by a `JuryAdministrator`; an `EXCUSE` or `EXEMPT` may be decided only by a `CourtClerk`. A decision made by the wrong office for the kind is rejected with `ERR_DISPOSITION_ROLE_MISMATCH` (HTTP 403). Deciding requires the disposition to still be `PENDING` and the underlying summons to be in `QUALIFIED_PENDING`; otherwise the request is an invalid state. On any decision the deciding actor's role is stamped into `decided_by_role`. A `DENIED` decision leaves the summons in `QUALIFIED_PENDING` and changes nothing else.

A `GRANTED` decision drives the summons by kind. A granted `EXCUSE` moves the summons from `QUALIFIED_PENDING` to the terminal `EXCUSED` state, and a granted `EXEMPT` moves it to the terminal `EXEMPT` state; both end panel eligibility. A granted `DEFER` is richer: it requires that the `requested_term_id` reference a term currently in either `DRAFT` or `OPEN` status, and it requires that the summons has not already been deferred too many times. A summons may be deferred at most twice — concretely, a `DEFER` may be granted only while the summons's `deferral_count` is below 2; granting a third would exceed the limit and is rejected with `ERR_DEFERRAL_LIMIT` (HTTP 409). When a `DEFER` is granted, the original summons moves from `QUALIFIED_PENDING` to the terminal `DEFERRED` state with its `deferred_to_term_id` set to the requested term, and the system cascades a fresh summons into being: a new summons in `SUMMONED` status is created on the requested term for the same juror, with a `badge_number` minted on that target term and a `deferral_count` equal to the original summons's `deferral_count` plus one. This is the deferral cycle — a deferred summons reissues as a new summons on a later term, where the juror re-qualifies and reports anew.

### 3.6. Failure to Appear and Disqualification

When a qualified juror does not show, a `CourtClerk` marks the summons as failed to appear, moving it from `QUALIFIED_PENDING` to the terminal `FAILED_TO_APPEAR` state. This action is gated temporally: it cannot be performed before the server clock has reached the term's `report_date`, and an attempt made too early is rejected with `ERR_BEFORE_REPORT_DATE` (HTTP 409). The summons must be in `QUALIFIED_PENDING`, or the attempt is an invalid state.

Marking a failure to appear sets off a chain of cascades. First, a **strike** record is created against the juror — an append-only row recording its `juror_id`, the `summons_id` on which the failure occurred, and a `source` of `FTA`. Then the juror's `fta_strike_count` is recomputed as the count of FTA-sourced strike rows for that juror. The disqualification test is a threshold with an inclusive boundary: the juror's `disqualified` flag is set true exactly when `fta_strike_count` is greater than or equal to the term's `fta_disqualify_threshold`. The boundary is inclusive — a count equal to the threshold disqualifies, and a count one below the threshold does not. When that flag flips to true, the cascade continues: a juror who was `QUALIFIED` is driven to `INELIGIBLE`, and the term's `pool_size` is recomputed downward to reflect the juror's removal from the draw pool. With the default threshold of 3, the third recorded failure is the one that disqualifies.

### 3.7. Trials, Panels, and Empaneling a Jury

A trial is created under a term by either a `JuryAdministrator` or a `Judge`, supplying a `caption` and the number of `required_jurors` the empaneled jury must hold (at least one). A new trial records its `service_term_id` and begins in `SCHEDULED` status. A `Judge` readies a trial for seating, advancing it from `SCHEDULED` to `READY`; this is permitted only while the trial is `SCHEDULED` and the term is `OPEN`, and it is the cross-entity gate that lets panels under that trial begin seating jurors. As empaneling proceeds the trial advances automatically: it moves from `READY` to `IN_TRIAL` when its panel fills, and from `IN_TRIAL` to `ADJOURNED` when that panel is dismissed.

A `Judge` creates a **panel** under a trial; the panel records its `service_term_id` and `trial_id`, begins `FORMING`, and carries a `target_size` of seats to fill. The `target_size` may be supplied at creation and otherwise defaults to the trial's `required_jurors`; it must be at least one. The panel's `seated_count` — the number of seat assignments on the panel whose `status` is `SEATED` — starts at zero. The panel remains `FORMING` until `seated_count` reaches `target_size`, becomes `SEATED` on empanel, and is terminal once `DISMISSED`.

Seating draws a reporting juror into an open seat. A `Judge` seats by naming the `summons_id` to seat and supplying `expected_panel_version` for the concurrency check of §2.6. Seating is hedged with several ordered conditions. The term must be `OPEN` (`ERR_TERM_NOT_OPEN`). The panel's trial must be in `READY`, or the seat is rejected with `ERR_TRIAL_NOT_READY` (HTTP 409). The summons being seated must be in `REPORTING` — meaning it has checked in and is not already occupying a seat on another panel — or the seat is rejected with `ERR_SUMMONS_NOT_REPORTING` (HTTP 409). The panel must still be `FORMING` with `seated_count` below `target_size`; an attempt to seat when `seated_count` already equals `target_size` is rejected with `ERR_PANEL_FULL` (HTTP 409). On a successful seat, a **panel assignment** is created in `SEATED` status recording its `panel_id` and the seated `summons_id`, with a `seat_index` equal to the panel's `seated_count` plus one (a monotone 1-based seat number); the panel's `seated_count` increments, the panel's `version` increments by one, and the seated summons advances from `REPORTING` to `SERVING`.

When that increment brings `seated_count` up to `target_size`, the panel fills: it auto-transitions from `FORMING` to `SEATED`, its trial advances from `READY` to `IN_TRIAL`, and an **estimated pay voucher** is issued for every `SEATED` summons on the panel, as described in §3.8.

### 3.8. Pay Vouchers — Estimated and Final

A **pay voucher** accounts for a juror's compensation. Each voucher records its `summons_id`, a `variant` of either `ESTIMATED` or `FINAL`, the computed `paid_days`, `attendance_cents`, `mileage_cents`, and `total_cents`. The two variants differ only in which check-ins they consider; the arithmetic is identical.

The voucher first determines `paid_days`: the lesser of the count of eligible check-ins and the term's `pay_day_cap`. The counted days are then the earliest `paid_days` eligible check-ins, ordered by `service_date` ascending with `created_at` ascending as the tie-break. Each counted check-in contributes day pay according to its `day_kind`: a `FULL` day contributes the term's `daily_pay_cents` and a `HALF` day contributes the term's `half_day_pay_cents`. The `attendance_cents` is the sum of day pay over the counted check-ins. Mileage follows a pinned rounding order: the per-day mileage is the juror's `round_trip_miles` multiplied by the term's `mileage_rate_cents`, rounded half-up to whole cents once per day; the `mileage_cents` is that per-day mileage multiplied by `paid_days`. Mileage is rounded per counted day and then summed — never summed first and rounded once. Finally, `total_cents` is `attendance_cents` plus `mileage_cents`.

The `ESTIMATED` voucher is issued when a panel fills (the `FORMING` to `SEATED` transition). Its eligible check-ins are all those recorded up to the seating instant; because the venire has not finished serving, any days accrued after seating are not in this voucher. The `FINAL` voucher is issued at release. Its eligible check-ins are all check-ins on the summons through release, so `paid_days` is recounted and recapped over the full set. Whenever post-seating service days exist, the final total is at least as large as the estimated total.

### 3.9. Pulling a Seat, Dismissal, and Release

Before a panel is full, a `Judge` can pull a seated juror back off a forming panel — an excuse-from-panel action that moves the summons from `SERVING` back to `REPORTING`. It is permitted only while the assignment is `SEATED` and the panel is still `FORMING` (a seat cannot be pulled from an already-empaneled panel). It sets the assignment's `status` to `EXCUSED_FROM_PANEL`, which frees the seat: the panel's `seated_count` decrements, the panel's `version` increments by one, and the juror returns to the reporting hall in `REPORTING`.

A `Judge` dismisses a panel, and the effect depends on the panel's state. Dismissing a `SEATED` panel moves it to the terminal `DISMISSED` state and advances its trial from `IN_TRIAL` to `ADJOURNED`; every `SEATED` summons on that panel remains `SERVING` and is not auto-released — each must be individually released afterward. Dismissing a `FORMING` panel also moves it to `DISMISSED`, but here the system cascades: every `SEATED` panel assignment on it is set to `EXCUSED_FROM_PANEL`, each occupying summons reverts from `SERVING` back to `REPORTING`, the panel's `seated_count` resets to zero, and the panel's `version` increments by one.

A `CourtClerk` releases a juror, moving the summons to the terminal `RELEASED` state and triggering the `FINAL` pay voucher. There are two valid release paths. A `SERVING` juror may be released once the panel they served on has been `DISMISSED` or its trial has `ADJOURNED`. A `REPORTING` juror who never took a seat — one holding no `SEATED` panel assignment — may also be released directly. In either case the release issues the `FINAL` voucher described in §3.8. A release requested from any other state is an invalid-state condition.

Reporting and audit views round out the workflows: the system exposes the qualification response, check-ins, dispositions, strikes, pay vouchers, and seat assignments belonging to a given summons; the strikes, summonses, and pool membership tied to a given juror; and the trials, panels, and summonses under a given term. Dispositions can also be filtered by their `requested_term_id` and by `decision`; summonses can be filtered by `status`, by `juror_id`, and by `deferred_to_term_id`; jurors can be filtered by `qualification_status` and by `disqualified`; panels and trials and assignments by `status`; and pay vouchers by `variant`. Every request body is finally checked for required fields, valid enum membership, and in-range numeric values; a missing field, a bad enum, or an out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. Authentication and authorization are evaluated first on every request, followed by existence checks, state checks, business and temporal rules, optimistic-concurrency checks, and finally request-body validation, in the priority order described throughout §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-terms` | Create a service term (DRAFT) | JuryAdministrator |
| GET | `/service-terms` | List service terms | JuryAdministrator, CourtClerk, Judge |
| GET | `/service-terms/{id}` | Get a service term including computed counters | JuryAdministrator, CourtClerk, Judge |
| POST | `/service-terms/{id}/open` | Open the term (DRAFT→OPEN) | JuryAdministrator |
| POST | `/service-terms/{id}/close` | Close the term (OPEN→CLOSED) | JuryAdministrator |
| POST | `/service-terms/{id}/draw` | Draw `count` jurors and issue summonses | JuryAdministrator |
| GET | `/service-terms/{id}/pool-projection` | What-if maximum mileage exposure for the qualified pool | JuryAdministrator |
| POST | `/service-terms/{id}/jurors` | Add a juror to the term pool (PENDING) | JuryAdministrator |
| GET | `/service-terms/{id}/jurors` | List jurors in a term pool | JuryAdministrator, CourtClerk |
| GET | `/jurors/{id}` | Get a juror | JuryAdministrator, CourtClerk, Juror |
| GET | `/jurors/{id}/summonses` | List summonses issued to a juror | JuryAdministrator, CourtClerk, Juror |
| POST | `/jurors/{id}/qualify` | Administrative qualification override (PENDING→QUALIFIED) | JuryAdministrator |
| GET | `/service-terms/{id}/summonses` | List summonses in a term | JuryAdministrator, CourtClerk |
| GET | `/summonses/{id}` | Get a summons | JuryAdministrator, CourtClerk, Juror |
| POST | `/summonses/{id}/qualification` | Submit the qualification questionnaire | Juror |
| GET | `/summonses/{id}/qualification` | Get the qualification response for a summons | JuryAdministrator, CourtClerk, Juror |
| POST | `/summonses/{id}/check-in` | Record a service-day check-in | CourtClerk |
| GET | `/summonses/{id}/check-ins` | List check-ins for a summons | JuryAdministrator, CourtClerk |
| POST | `/summonses/{id}/release` | Release a reporting/serving juror (→RELEASED) | CourtClerk |
| POST | `/summonses/{id}/mark-fta` | Mark a no-show as FAILED_TO_APPEAR | CourtClerk |
| GET | `/summonses/{id}/pay-vouchers` | List pay vouchers for a summons | JuryAdministrator, CourtClerk, Juror |
| POST | `/summonses/{id}/dispositions` | Request DEFER/EXCUSE/EXEMPT (PENDING) | Juror |
| GET | `/summonses/{id}/dispositions` | List dispositions for a summons | JuryAdministrator, CourtClerk, Juror |
| POST | `/dispositions/{id}/decide` | Decide a disposition (PENDING→GRANTED/DENIED) | CourtClerk, JuryAdministrator |
| GET | `/dispositions/{id}` | Get a disposition | JuryAdministrator, CourtClerk, Juror |
| GET | `/dispositions` | List dispositions filtered by requested deferral term | JuryAdministrator, CourtClerk |
| POST | `/service-terms/{id}/trials` | Create a trial under a term (SCHEDULED) | JuryAdministrator, Judge |
| GET | `/service-terms/{id}/trials` | List trials in a term | JuryAdministrator, CourtClerk, Judge |
| GET | `/trials/{id}` | Get a trial | JuryAdministrator, CourtClerk, Judge |
| POST | `/trials/{id}/ready` | Mark a trial READY for seating (SCHEDULED→READY) | Judge |
| POST | `/trials/{id}/panels` | Create a forming panel for a trial (FORMING) | Judge |
| GET | `/trials/{id}/panels` | List panels for a trial | JuryAdministrator, CourtClerk, Judge |
| GET | `/service-terms/{id}/panels` | List panels in a term | JuryAdministrator, CourtClerk, Judge |
| GET | `/panels/{id}` | Get a panel including seated_count | JuryAdministrator, CourtClerk, Judge |
| POST | `/panels/{id}/seat` | Seat a REPORTING summons into a forming panel | Judge |
| POST | `/panels/{id}/dismiss` | Dismiss a panel (SEATED→DISMISSED or FORMING→DISMISSED) | Judge |
| GET | `/panels/{id}/assignments` | List seat assignments on a panel | JuryAdministrator, CourtClerk, Judge |
| GET | `/summonses/{id}/assignments` | List seat assignments for a summons | JuryAdministrator, CourtClerk, Judge |
| POST | `/panel-assignments/{id}/excuse-from-panel` | Pull a seated juror off a forming panel (SERVING→REPORTING) | Judge |
| GET | `/panel-assignments/{id}` | Get a panel assignment | JuryAdministrator, CourtClerk, Judge |
| GET | `/jurors/{id}/strikes` | List FTA strikes for a juror | JuryAdministrator, CourtClerk |
| GET | `/summonses/{id}/strikes` | List strikes recorded on a summons | JuryAdministrator, CourtClerk |
| POST | `/_clock/set_current_utc` | Set the server clock (test-driving) | JuryAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_DISPOSITION_ROLE_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERM_NOT_OPEN` | 409 |
| `ERR_BEFORE_REPORT_DATE` | 409 |
| `ERR_DUPLICATE_SUMMONS` | 409 |
| `ERR_DUPLICATE_SERVICE_DATE` | 409 |
| `ERR_TRIAL_NOT_READY` | 409 |
| `ERR_SUMMONS_NOT_REPORTING` | 409 |
| `ERR_PANEL_FULL` | 409 |
| `ERR_DEFERRAL_LIMIT` | 409 |
| `ERR_POOL_EXHAUSTED` | 409 |
| `ERR_STALE_PANEL_VERSION` | 412 |
| `ERR_STALE_TERM_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
