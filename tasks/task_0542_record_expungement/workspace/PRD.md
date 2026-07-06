# Record Expungement API — Product Requirements Document

## 1. Introduction

Clearing a criminal record is rarely a single act; it is a regulated journey that threads eligibility law, court procedure, agency notice, judicial discretion, and downstream data cleanup into one accountable chain. This document specifies the Record Expungement API, a backend service that governs that chain end to end: screening individual convictions and arrests against statutory waiting periods, assembling and filing petitions, notifying the agencies entitled to object, scheduling and holding hearings, entering and distributing the sealing order, and confirming that every background-check recipient has actually purged the sealed record.

The system is built for four kinds of actors working the same case from different vantage points — the petitioner who owns the record, the court clerk who drives the process, the agencies who may object, and the judge who rules — and it must keep their views consistent at every step. Two themes recur throughout the requirements below and deserve early emphasis. First, time is deterministic: waiting periods and objection windows are measured against a server-controlled logical clock, never wall-clock time, so that eligibility and deadlines are reproducible. Second, money and record-state are conserved: filing fees paid can be refunded on withdrawal without drift, and a record that is sealed can be unsealed cleanly if the order is later vacated. Getting these invariants right is the central engineering challenge of the platform.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. Where a rule is stated here, it is not repeated in full for each workflow in Section 3; readers should treat Sections 2 and 3 as complementary.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the roles the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Petitioner`, `Clerk`, `Agency`, and `Judge`.

- A `Petitioner` is the individual seeking expungement and owns their own criminal records, petitions, fee payments, and fee-waiver requests. When `X-User-Role` is `Petitioner`, `X-User-ID` is the `id` of the acting `Petitioner` entity; ownership checks on any resource that references a petitioner compare that resource's `petitioner_id` to `X-User-ID`. A petitioner acting on a resource whose `petitioner_id` does not equal their `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- A `Clerk` operates the court's intake and process workflow. When `X-User-Role` is `Clerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`.
- An `Agency` is a notified party (a district attorney's office, an arresting agency, or a state repository) that may file objections during the objection window. When `X-User-Role` is `Agency`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- A `Judge` presides over hearings and enters or vacates court orders. When `X-User-Role` is `Judge`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity.

Role authority is summarized in the endpoint table of Section 4; the surrounding narrative in Section 3 describes which role initiates each transition. Read operations (all `GET` endpoints) are available to every role.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint says otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered set and `has_more` indicates whether items remain beyond the current page.

### 2.4. The Logical Clock and Deterministic Time

All time-dependent rules in this system — record waiting periods, objection deadlines, and the timestamps stamped onto served notifications, filed objections, and entered orders — are evaluated against a server-controlled **logical clock**, never the host's wall-clock. The clock starts at `2026-05-01T00:00:00Z` when the server boots and only ever changes when an operator explicitly sets it; it never silently advances or falls back to real time. An administrative test-driving capability lets an operator move the clock to a supplied `to_iso8601` instant. Because the clock is the sole source of "now", eligibility screening and window checks are fully reproducible.

Wherever this document refers to "the current time", "now", or a resource being served, filed, or entered "at" a moment, it means the value of this logical clock at the instant the operation is processed.

### 2.5. Common Resource Properties

Every resource carries a server-minted `id` formatted as a UUID (with no type prefix) and a `created_at` timestamp: an ISO 8601 UTC value with three fractional digits marking when the resource was first created.

Most resources — `Petitioner`, `CriminalRecord`, `Petition`, `FeeWaiver`, `AgencyNotification`, `Objection`, `Hearing`, `CourtOrder`, and `SealingDistribution` — additionally carry two system-managed fields: an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and an integer `version` that starts at its initial value and increments by one on every mutation. The `version` supports optimistic concurrency control as described in Section 2.8.

Four resource types are configuration or snapshot records and deliberately omit both mutable fields: `Courtroom`, `Judge`, `BackgroundVendor`, and `PetitionItem` carry only `id` and `created_at`. They have no `updated_at` and no `version`. Note in particular that a `BackgroundVendor` maintains a `records_updated_count` counter that grows over time even though the vendor record itself exposes no `version` or `updated_at`.

### 2.6. Cascading State Propagation and Consistency

Many operations in this domain do not touch a single resource in isolation; a single client action can drive a chain of state changes across several entities. When a court order is granted, for example, the effect propagates from the order to the petition, from the petition to its eligible records, and from each sealed record outward to a set of distribution rows — a multi-hop cascade. Whenever the server automatically transitions a resource as a downstream consequence of another operation, that automatic transition is a genuine mutation: it refreshes the affected resource's `updated_at` and increments its `version`, exactly as an explicit client-initiated change would. These server-driven propagations happen without the client issuing a separate request against the downstream resource.

The system's consistency model is immediate: all cascaded effects of an operation are applied before the response is returned, so a client never observes a half-applied cascade. Section 3 specifies each cascade in full; this subsection establishes only the general rule that every hop in a cascade mutates its target with the same bookkeeping (`updated_at`, `version`) as a direct write.

### 2.7. Nested Reference Resolution

Requests routinely name resources both in the URL path and in the request body (for example, a petition creation names a `petitioner_id` and a list of records; a hearing creation names a `courtroom_id` and a `judge_id`). The server resolves every such reference — path identifiers and body foreign keys alike — in left-to-right order, and rejects the request at the first identifier that does not resolve to an existing resource. The rejection carries the not-found error specific to the missing entity: `ERR_PETITIONER_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, or `ERR_COURT_ORDER_NOT_FOUND` for those aggregates, and the generic `ERR_NOT_FOUND` for a missing courtroom, judge, background vendor, petition item, agency notification, objection, fee waiver, or sealing distribution. All of these are HTTP 404. Existence is always checked before any business rule that depends on the referenced resource's state.

### 2.8. Optimistic Concurrency Control on Hearing Scheduling

Scheduling and rescheduling a petition's hearing is the one operation guarded by optimistic concurrency control, because a reschedule legitimately supersedes a petition's prior scheduled hearing and the system must not let a client overwrite a hearing arrangement it never observed. The hearing-scheduling request therefore requires a non-optional `expected_petition_version` field carrying the `version` of the target `Petition` that the client last read. Before the hearing is created, the server compares `expected_petition_version` against the petition's current `version`. If they do not match — that is, if another writer has advanced the petition's `version` since the client last observed it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no hearing is created or superseded. No other endpoint accepts or requires a version field; only hearing scheduling participates in this check.

### 2.9. Monetary Precision and the Fee Ledger

All monetary quantities in the system — incomes, asset balances, fees, thresholds, and ledger totals — are stored and computed as integer numbers of **cents**. Every fee computation that involves multiplication (a base fee times a disposition multiplier times the electronic-filing surcharge, or a poverty line times its multiplier) is rounded to a whole number of cents using the **round half up** convention: a fractional cent of exactly one half rounds away from zero to the next whole cent. Pure additions and subtractions in the ledger use exact integer arithmetic and require no rounding.

The petitioner-level fee ledger is a conserved system. Each `Petitioner` carries two running totals, `fee_paid_cents` and `fee_refunded_cents`, both starting at zero. The quantity that must never drift is the petitioner's net fees — the amount paid minus the amount refunded: a payment followed by the withdrawal that refunds it returns the net back to its pre-payment value. Section 3 details exactly when each total moves.

### 2.10. Order of Request Validation

When several rules could reject a request, they are evaluated in a fixed precedence so that failures are reported deterministically. The order is:

1. **Authentication** — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted to call the endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Body well-formedness** — on every mutating endpoint, required fields are present, enum fields hold in-range values, integer fields are non-negative, `household_size` is at least 1, and, for a hearing, `scheduled_end` is strictly later than `scheduled_start`; otherwise `ERR_VALIDATION` (422).
4. **Existence** — every path id and body foreign key resolves, checked left-to-right per Section 2.7, else the appropriate 404.
5. **Ownership** — where the acting role is `Petitioner`, `X-User-ID` equals the target resource's `petitioner_id`, else `ERR_NOT_RESOURCE_OWNER` (403). This applies to attaching a criminal record, assembling a petition, paying a filing fee, requesting a fee waiver, and withdrawing a petition.
6. **State** — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
7. **Concurrency** — for hearing scheduling, `expected_petition_version` matches the petition's `version`, else `ERR_STALE_VERSION` (412).
8. **Reference integrity** — cross-entity ownership and jurisdiction constraints (see Sections 3.3 and 3.7), else `ERR_RECORD_NOT_OWNED` or `ERR_JURISDICTION_MISMATCH` (both 409).
9. **Temporal availability** — courtroom and judge scheduling conflicts and objection-window checks (Sections 3.6 and 3.7), else `ERR_COURTROOM_UNAVAILABLE`, `ERR_JUDGE_UNAVAILABLE`, `ERR_OBJECTION_WINDOW_CLOSED`, or `ERR_OBJECTION_WINDOW_OPEN` (all 409).
10. **Compliance gates** — the safety preconditions of each transition (records screened, at least one eligible record, notifications cleared, hearing held, retry cap, waiver eligibility), else the corresponding 409 error named in Section 3.
11. **Filing-fee sufficiency** — for filing, the fee is waived or fully paid, else `ERR_FILING_FEE_UNPAID` (402).

A rule earlier in this list, when it fails, masks any later rule that would also have failed.

## 3. Business Logic & Workflows

### 3.1. Petitioners, Configuration Records, and the Fee Ledger

A case begins with a `Petitioner` profile. A `Clerk` creates one by supplying the petitioner's `full_name`, `date_of_birth`, `annual_income_cents` (self-reported annual household income in cents), `household_size` (the number of persons in the household, which must be at least 1), and an optional `monthly_liquid_assets_cents` (liquid assets in cents, defaulting to 0 when omitted). On creation the two ledger totals, `fee_paid_cents` and `fee_refunded_cents`, are both initialized to 0. The petitioner record is readable by any role and, when read, exposes the current ledger.

Alongside petitioners, a clerk registers the fixed configuration resources the process later depends on. A **courtroom** is created with a `name` and a `jurisdiction_code` identifying the jurisdiction it serves. A **judge** is created with a `name` and the `jurisdiction_code` they preside over. A **background vendor** — a downstream background-check provider — is registered with a `name` and an `api_endpoint` (the vendor's callback URL for sealing updates); its `records_updated_count` starts at 0 and later counts the sealing distributions the vendor has acknowledged. These three record types are configuration snapshots and, per Section 2.5, carry only `id` and `created_at`.

The fee ledger moves at two moments. When a filing-fee payment is recorded against a petition, the paid `amount_cents` is added both to that petition's `amount_paid_cents` and to the owning petitioner's `fee_paid_cents`. When a petition is later withdrawn (Section 3.3), the petition's entire `amount_paid_cents` is added to the petitioner's `fee_refunded_cents` as compensation, conserving the net-fee invariant of Section 2.9. Paying a fee is an action a `Petitioner` may take on their own petition, or a `Clerk` on their behalf.

### 3.2. Criminal Records and Eligibility Screening

A criminal record is attached to a petitioner by that `Petitioner` (for their own `petitioner_id`) or by a `Clerk`. The payload names the `petitioner_id`, an `offense_code` (free-text statutory code), an `offense_class`, a `disposition`, a `disposition_date`, and — only when the disposition is `CONVICTED` — a `sentence_completion_date` (otherwise null). The `offense_class` is one of `INFRACTION`, `MISDEMEANOR`, `FELONY_CLASS_C`, `FELONY_CLASS_B`, `FELONY_CLASS_A`, or `VIOLENT_FELONY`; the `disposition` is one of `CONVICTED`, `DISMISSED`, `ARREST_ONLY`, or `ACQUITTED`. A freshly attached record enters the `UNSCREENED` state. Its `status` thereafter is one of `UNSCREENED`, `ELIGIBLE`, `INELIGIBLE`, or `SEALED`. Records can be fetched individually and listed with optional filters on `petitioner_id` and `status`.

**Screening** is performed by a `Clerk` and is the operation that decides eligibility. Screening first fixes the base date from which the waiting period runs: for a `CONVICTED` disposition the base date is the `sentence_completion_date`; for a `DISMISSED`, `ARREST_ONLY`, or `ACQUITTED` disposition — where no sentence exists — the base date is the `disposition_date`. Note that for two records with identical dates, the convicted (sentence-based) path and the non-convicted (disposition-based) path can yield different results because they read a different date field. The record's `eligible_on` — the earliest date the record may be expunged — is that base date advanced by a whole number of calendar years determined by the offense class: 1 year for an `INFRACTION`, 2 years for a `MISDEMEANOR`, 3 years for a `FELONY_CLASS_C`, 5 years for a `FELONY_CLASS_B`, and 7 years for a `FELONY_CLASS_A`.

Screening then classifies the record. A `VIOLENT_FELONY` is never eligible: the record becomes `INELIGIBLE`, its `ineligible_reason` is set to `NEVER_ELIGIBLE`, and `eligible_on` is left null. Otherwise the system compares the logical clock to `eligible_on`: if the current time is at or after `eligible_on` (the boundary is inclusive — the exact `eligible_on` instant already qualifies), the record becomes `ELIGIBLE`. If the current time is strictly before `eligible_on`, the record becomes `INELIGIBLE` with `ineligible_reason` set to `WAITING_PERIOD`, and `eligible_on` is retained so the record can be re-screened later. A record that was `INELIGIBLE` for `WAITING_PERIOD` may be screened again once the clock has reached its `eligible_on`; at that point the same non-violent-and-clock-at-or-past-`eligible_on` conditions move it from `INELIGIBLE` to `ELIGIBLE`. The two other `status` values — `SEALED` and the return from `SEALED` back to `ELIGIBLE` — are reached only through court-order cascades and vacatur (Sections 3.8 and 3.9), never through screening.

### 3.3. Assembling and Screening a Petition

A `Petition` is the vehicle that carries a set of a petitioner's records through the court. It is assembled by the owning `Petitioner` or by a `Clerk`, naming the `petitioner_id`, the `jurisdiction_code` the petition is filed in, and a `record_ids` list identifying which of the petitioner's records to include. Creating the petition places it in the `DRAFT` state and creates one `PetitionItem` junction row per entry in `record_ids`, each capturing a `petition_id` and a `record_id`. As a reference-integrity guard, every `record_id` supplied must belong to the same `petitioner_id` as the petition; a record owned by a different petitioner is rejected with `ERR_RECORD_NOT_OWNED` (409). A petition's `status` progresses through `DRAFT`, `SCREENED`, `FILED`, `OBJECTION_REVIEW`, and `HEARING_SET`, terminating in `GRANTED`, `DENIED`, or `WITHDRAWN`. Petitions and their items are individually retrievable and listable — petitions filter by `petitioner_id`, `jurisdiction_code`, and `status`; items filter by `petition_id` or `record_id`.

Petition status changes, like the status changes of notifications, objections, hearings, fee waivers, and distributions, are driven through a transition request that names the desired target state in a `to_status` field. Advancing a petition from `DRAFT` to `SCREENED` is a `Clerk` action and requires that the petition hold at least one `PetitionItem` and that every item's underlying record has already been screened — that is, each record's `status` is either `ELIGIBLE` or `INELIGIBLE`. If any included record is still `UNSCREENED`, the transition is rejected with `ERR_RECORDS_NOT_SCREENED` (409). On reaching `SCREENED`, the system snapshots each item and computes the provisional fee. For each `PetitionItem` it records `eligibility_at_screening` — the `ELIGIBLE` or `INELIGIBLE` state of its record at that moment — and `fee_at_screening_cents`, the per-record fee for that item. The petition's `provisional_fee_cents` is the sum of the per-record fees over **all** items regardless of eligibility.

The per-record fee is computed as follows: take the base fee in cents for the record's offense class — 5000 for `INFRACTION`, 12000 for `MISDEMEANOR`, 18000 for `FELONY_CLASS_C`, 25000 for `FELONY_CLASS_B`, 30000 for `FELONY_CLASS_A`, and 30000 for `VIOLENT_FELONY` — multiply it by the disposition multiplier (1.0 for `CONVICTED`, 0.5 for `DISMISSED`, 0.25 for `ARREST_ONLY`, and 0.10 for `ACQUITTED`), then multiply by 1.075 to add the 7.5% electronic-filing surcharge, and round the result to a whole number of cents using round half up. The rounding order is fixed: each per-record fee is rounded to whole cents first, and only then are the rounded per-record fees summed. The fees are never summed before rounding.

A petitioner may abandon a petition at several points by withdrawing it, which is an action reserved to the owning `Petitioner` and always moves the petition to `WITHDRAWN`. Withdrawing from `DRAFT` has no financial or notification side effects. Withdrawing from `SCREENED` refunds any fee already paid: the petition's `amount_paid_cents` is added to the petitioner's `fee_refunded_cents`. Withdrawing from `FILED` likewise refunds the paid amount and additionally clears the case's agency notices — every `AgencyNotification` of the petition that is not already `CLEARED` is moved to `CLEARED`. Withdrawing from `HEARING_SET` refunds the paid amount and vacates the pending hearing — any `SCHEDULED` hearing of the petition is moved to `VACATED`.

### 3.4. Fee Waivers

A petitioner who cannot afford the filing fee may request a `FeeWaiver`, an action available to the owning `Petitioner` or a `Clerk`. The request names the `petitioner_id` and the `petition_id`, enters the `REQUESTED` state, and immediately triggers an income determination. Its `status` is one of `REQUESTED`, `GRANTED`, `DENIED`, or `SUPERSEDED`. If a newer waiver is requested for the same petition, the earlier still-`REQUESTED` waiver for that petition is automatically moved to `SUPERSEDED`. Fee waivers are retrievable and listable, filtered by `petitioner_id` or `petition_id`.

The determination is computed from the requesting petitioner's finances at request time and recorded on the waiver as `determination_basis` (either `INCOME_UNDER_125` or `OVER_THRESHOLD`) together with the `income_threshold_cents` used. The system first computes the household poverty line in cents as 1,500,000 plus 530,000 for each household member beyond the first — that is, 1,500,000 plus (the petitioner's `household_size` minus 1) times 530,000. It then sets `income_threshold_cents` to that poverty line multiplied by 1.25 (the 125% threshold), rounded to whole cents using round half up. The basis is `INCOME_UNDER_125` when the petitioner's `annual_income_cents` is less than or equal to `income_threshold_cents` **and** their `monthly_liquid_assets_cents` is less than or equal to the asset cap of 200,000 cents; both bounds are inclusive. If either condition fails, the basis is `OVER_THRESHOLD`.

A `Clerk` decides the waiver. Granting it is permitted only when `determination_basis` is `INCOME_UNDER_125`; an attempt to grant a waiver whose basis is `OVER_THRESHOLD` is rejected with `ERR_WAIVER_NOT_ELIGIBLE` (409). When a waiver is granted, the referenced petition's `fee_waived` flag is set to true and its `fee_due_cents` is set to 0. A clerk may instead deny the waiver, which simply moves it to `DENIED` with no effect on the petition.

### 3.5. Filing the Petition and Notifying the Agencies

Filing carries a `SCREENED` petition to `FILED` and is a `Clerk` action. Two gates apply. First, the petition must contain at least one item whose `eligibility_at_screening` is `ELIGIBLE`; a petition with no eligible records cannot be filed and is rejected with `ERR_NO_ELIGIBLE_RECORDS` (409). Second, the filing fee must be satisfied. On filing, the system computes `final_fee_cents` as the sum of the per-record fees — using the same per-record formula and round-then-sum order as in Section 3.3 — but summed only over the items whose `eligibility_at_screening` is `ELIGIBLE`; because ineligible items drop out, the final fee is at most the provisional fee. The petition's `fee_due_cents` is then set to 0 if `fee_waived` is true, and otherwise to the final fee minus `amount_paid_cents`, floored at 0 so it never goes negative. Filing is permitted only if the petition's fee is waived, or the `amount_paid_cents` already recorded is at least `final_fee_cents`; if neither holds, filing is rejected with `ERR_FILING_FEE_UNPAID` (402).

On a successful filing, the system opens the objection process by creating three `AgencyNotification` rows for the petition, one for each `agency_type`: `DA`, `ARRESTING_AGENCY`, and `STATE_REPOSITORY`. Each notification is created in the `PENDING` state; its `status` will move through `PENDING`, `SERVED`, `OBJECTED`, and `CLEARED`. Notifications are retrievable and listable, filtered by `petition_id` and `status`.

A `Clerk` serves a pending notification, which stamps `served_at` with the current logical-clock time and computes the `objection_deadline` as `served_at` plus the fixed objection window (`OBJECTION_WINDOW_DAYS` days), marking the end of the period during which that agency may object. After the window has elapsed, the clerk clears the notification: clearing is permitted only when the current time is at or after `objection_deadline` (attempting to clear before the deadline is rejected with `ERR_OBJECTION_WINDOW_OPEN`, 409) and only when no objection is still outstanding (`REQUESTED`) on that notification. A notification also reaches `CLEARED` automatically when an objection against it is overruled, and — as noted in Section 3.3 — when its petition is withdrawn from `FILED`.

### 3.6. Objections and Review

Only an `Agency` may file an objection, and only against a `SERVED` notification within its window. Filing supplies free-text `grounds`; the objection is created in the `REQUESTED` state with `filed_at` stamped from the logical clock, and its `status` thereafter is one of `REQUESTED`, `SUSTAINED`, or `OVERRULED`. Objections are retrievable and listable, filtered by `notification_id` and `status`. The objection may be filed only if the current time is at or before the notification's `objection_deadline`; an objection filed after the deadline is rejected with `ERR_OBJECTION_WINDOW_CLOSED` (409). A successfully filed objection cascades: the parent notification moves from `SERVED` to `OBJECTED`, and that in turn drives the petition from `FILED` to `OBJECTION_REVIEW`.

A `Clerk` resolves an objection one of two ways. Sustaining it terminates the case: the petition, then in `OBJECTION_REVIEW`, is moved to `DENIED`. Overruling it clears the path back: the parent notification moves from `OBJECTED` to `CLEARED`, and then, provided no other notification of the same petition is still `OBJECTED`, the petition reverts from `OBJECTION_REVIEW` back to `FILED`. If another objected notification remains, the petition stays in `OBJECTION_REVIEW` until it too is resolved.

### 3.7. Scheduling the Hearing

Once a petition is `FILED` and every one of its agency notifications is `CLEARED`, a `Clerk` schedules the hearing, which moves the petition from `FILED` to `HEARING_SET` and creates a `Hearing` in the `SCHEDULED` state. The scheduling payload names the `courtroom_id`, the `judge_id`, the `scheduled_start` (inclusive) and `scheduled_end` (exclusive) of the hearing, and the `expected_petition_version` required by the optimistic-concurrency check of Section 2.8. If any notification of the petition is not yet `CLEARED`, scheduling is rejected with `ERR_NOTIFICATIONS_NOT_CLEARED` (409). A hearing's `status` is one of `SCHEDULED`, `HELD`, `VACATED`, or `SUPERSEDED`; hearings are retrievable and listable, filtered by `petition_id`, `courtroom_id`, `judge_id`, and `status`.

Three placement checks apply. First, jurisdiction must line up: the chosen courtroom's `jurisdiction_code` and the chosen judge's `jurisdiction_code` must both equal the petition's `jurisdiction_code`, else the request is rejected with `ERR_JURISDICTION_MISMATCH` (409). Second, the courtroom must be free. A courtroom conflict is evaluated with buffer semantics against every other `SCHEDULED` hearing in that room: two hearings conflict if their time ranges overlap or merely touch at a boundary — a hearing beginning exactly when another ends still conflicts, reflecting a changeover buffer — and a conflict is rejected with `ERR_COURTROOM_UNAVAILABLE` (409). Third, the judge must be free. A judge conflict is evaluated with half-open semantics against every other `SCHEDULED` hearing for that judge: each hearing occupies the interval from its `scheduled_start` (inclusive) up to but not including its `scheduled_end`, so two hearings conflict only when these half-open intervals genuinely overlap; back-to-back hearings that merely share a boundary instant do not conflict. A judge conflict is rejected with `ERR_JUDGE_UNAVAILABLE` (409).

A petition already in `HEARING_SET` may be rescheduled by a `Clerk`, which stays in `HEARING_SET` while replacing the hearing. A reschedule carries the same `expected_petition_version` optimistic-concurrency check, the same jurisdiction requirement, and the same courtroom-buffer and judge-half-open temporal checks as the initial scheduling. On success, the petition's prior `SCHEDULED` hearing is moved to `SUPERSEDED` and a replacement `Hearing` is created in `SCHEDULED`. Because a reschedule advances the petition's `version`, a second scheduling request that still carries an `expected_petition_version` the server has already moved past is a stale-view write and fails the version check with `ERR_STALE_VERSION` (412) rather than silently superseding a hearing the client never saw. A `Clerk` marks a scheduled hearing as `HELD` when it takes place, or `VACATED` if it is called off.

### 3.8. The Court Order and Record Sealing

After a hearing is `HELD`, a `Judge` enters the court order, supplying a `disposition` of either `GRANTED` or `DENIED`. Entering an order is permitted only when the hearing is `HELD`; an attempt to enter an order against a hearing that has not been held is rejected with `ERR_HEARING_NOT_HELD` (409). The order is created carrying its `petition_id`, `hearing_id`, and `disposition`, with `entered_at` stamped from the logical clock, in the `ENTERED` state; a court order's `status` is one of `ENTERED`, `DISTRIBUTED`, or `VACATED`. Court orders are retrievable and listable, filtered by `petition_id` and `hearing_id`.

A `DENIED` order simply moves the petition from `HEARING_SET` to `DENIED`; no records are sealed. A `GRANTED` order drives the signature cascade of the whole system. First, the petition moves from `HEARING_SET` to `GRANTED`. Second, every item of that petition whose `eligibility_at_screening` is `ELIGIBLE` has its underlying criminal record moved from `ELIGIBLE` to `SEALED`. Third, each newly sealed record fans out a set of `SealingDistribution` rows attached to the order: one row for each agency recipient — `DA`, `ARRESTING_AGENCY`, and `STATE_REPOSITORY` — plus one row for each registered `BackgroundVendor`, every row created in the `QUEUED` state. Each distribution records a `recipient_type` (`DA`, `ARRESTING_AGENCY`, `STATE_REPOSITORY`, or `BACKGROUND_VENDOR`) and a `recipient_ref`: for a background-vendor row the `recipient_ref` is the `BackgroundVendor`'s `id`, while for an agency row it is the agency code string rather than a canonical foreign key.

A `Judge` may later vacate a granted order to undo the sealing. Vacating is defined for an order whose `disposition` is `GRANTED`; vacating an order from the `ENTERED` state requires that disposition and otherwise is rejected with `ERR_INVALID_STATE` (409), while an order already `DISTRIBUTED` may be vacated directly. Either way, vacatur is a compensation: every record of the order's petition that is currently `SEALED` is moved back to `ELIGIBLE` (unsealed), restoring the conservation invariant that a vacated grant leaves no record sealed. When vacating an order still in `ENTERED`, every non-terminal `SealingDistribution` of the order — those not already acknowledged or cancelled — is moved to `CANCELLED`.

### 3.9. Distributing the Sealing Order and Vendor Acknowledgement

Each `SealingDistribution` represents the delivery of the sealing order to one recipient and moves through its own small lifecycle under `Clerk` control. Its `status` is one of `QUEUED`, `SENT`, `ACKNOWLEDGED`, `FAILED`, or `CANCELLED`, and it tracks an `attempt_count` (the number of send retries consumed), starting at 0. Distributions are retrievable and listable, filtered by `court_order_id`, `recipient_type`, and `status`.

A clerk sends a queued distribution, moving it from `QUEUED` to `SENT`. A sent distribution may be acknowledged, moving it to `ACKNOWLEDGED`; when the acknowledged distribution's `recipient_type` is `BACKGROUND_VENDOR`, the `BackgroundVendor` identified by the distribution's `recipient_ref` has its `records_updated_count` incremented by one. Acknowledgement also bubbles up to the order: once every sibling distribution of the same court order is `ACKNOWLEDGED` and that order's `disposition` is `GRANTED`, the order moves from `ENTERED` to `DISTRIBUTED`. Alternatively, a sent distribution that fails to deliver is moved to `FAILED`. A failed distribution may be retried, moving it back to `QUEUED`, but only while its `attempt_count` is below the maximum of 2 retries; each retry increments `attempt_count` by one. A retry attempted when `attempt_count` has already reached 2 is rejected with `ERR_MAX_RETRIES_EXCEEDED` (409). The `ACKNOWLEDGED` and `CANCELLED` states are terminal for a distribution.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify or transition an existing resource, including recording a fee payment or advancing a state machine, return `200 OK`. The one exception in spirit is hearing scheduling, which creates a new `Hearing` resource and therefore returns `201 Created`, and objection filing and order entry, which likewise create new resources and return `201 Created`. All list and single-fetch reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/expungement/courtrooms` | Create a courtroom | Clerk |
| GET | `/expungement/courtrooms/{id}` | Get a courtroom | All roles |
| POST | `/expungement/judges` | Create a judge | Clerk |
| GET | `/expungement/judges/{id}` | Get a judge | All roles |
| POST | `/expungement/background-vendors` | Register a background-check vendor | Clerk |
| GET | `/expungement/background-vendors/{id}` | Get a background vendor | All roles |
| POST | `/expungement/petitioners` | Create a petitioner profile | Clerk |
| GET | `/expungement/petitioners/{id}` | Get a petitioner (includes fee ledger) | All roles |
| POST | `/expungement/criminal-records` | Attach a criminal record to a petitioner | Petitioner, Clerk |
| GET | `/expungement/criminal-records/{id}` | Get a criminal record | All roles |
| GET | `/expungement/criminal-records` | List criminal records (filter by petitioner, status) | All roles |
| POST | `/expungement/criminal-records/{id}/screen` | Run eligibility screening on a record | Clerk |
| POST | `/expungement/petitions` | Assemble a petition from a petitioner's records | Petitioner, Clerk |
| GET | `/expungement/petitions/{id}` | Get a petition (status + fee fields) | All roles |
| GET | `/expungement/petitions` | List petitions (filter by petitioner, jurisdiction, status) | All roles |
| GET | `/expungement/petition-items/{id}` | Get a petition item (screening snapshot) | All roles |
| GET | `/expungement/petition-items` | List petition items (filter by petition or record) | All roles |
| POST | `/expungement/petitions/{id}/transition` | Advance petition status (SCREENED, FILED, WITHDRAWN) | Petitioner, Clerk |
| POST | `/expungement/petitions/{id}/pay-fee` | Record a filing-fee payment | Petitioner, Clerk |
| POST | `/expungement/petitions/{id}/hearings` | Schedule (or reschedule) the petition's hearing | Clerk |
| POST | `/expungement/fee-waivers` | Request a fee waiver for a petition | Petitioner, Clerk |
| GET | `/expungement/fee-waivers/{id}` | Get a fee waiver | All roles |
| GET | `/expungement/fee-waivers` | List fee waivers (filter by petitioner or petition) | All roles |
| POST | `/expungement/fee-waivers/{id}/transition` | Decide a fee waiver (GRANTED / DENIED) | Clerk |
| GET | `/expungement/agency-notifications/{id}` | Get an agency notification | All roles |
| GET | `/expungement/agency-notifications` | List agency notifications (filter by petition) | All roles |
| POST | `/expungement/agency-notifications/{id}/transition` | Advance a notification (SERVED, CLEARED) | Clerk |
| POST | `/expungement/agency-notifications/{id}/objections` | File an objection within the window | Agency |
| GET | `/expungement/objections/{id}` | Get an objection | All roles |
| GET | `/expungement/objections` | List objections (filter by notification) | All roles |
| POST | `/expungement/objections/{id}/transition` | Resolve an objection (SUSTAINED / OVERRULED) | Clerk |
| GET | `/expungement/hearings/{id}` | Get a hearing | All roles |
| GET | `/expungement/hearings` | List hearings (filter by petition, courtroom, or judge) | All roles |
| POST | `/expungement/hearings/{id}/transition` | Advance a hearing (HELD, VACATED) | Clerk |
| POST | `/expungement/hearings/{id}/order` | Enter the court order for a held hearing | Judge |
| GET | `/expungement/court-orders/{id}` | Get a court order | All roles |
| GET | `/expungement/court-orders` | List court orders (filter by petition or hearing) | All roles |
| POST | `/expungement/court-orders/{id}/vacate` | Vacate a granted order (unseal + cancel distributions) | Judge |
| GET | `/expungement/sealing-distributions/{id}` | Get a sealing distribution | All roles |
| GET | `/expungement/sealing-distributions` | List sealing distributions (filter by order) | All roles |
| POST | `/expungement/sealing-distributions/{id}/transition` | Advance a distribution (SENT, ACKNOWLEDGED, FAILED, QUEUED-retry) | Clerk |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | Clerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_PETITIONER_NOT_FOUND` | 404 |
| `ERR_RECORD_NOT_FOUND` | 404 |
| `ERR_PETITION_NOT_FOUND` | 404 |
| `ERR_HEARING_NOT_FOUND` | 404 |
| `ERR_COURT_ORDER_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RECORD_NOT_OWNED` | 409 |
| `ERR_JURISDICTION_MISMATCH` | 409 |
| `ERR_COURTROOM_UNAVAILABLE` | 409 |
| `ERR_JUDGE_UNAVAILABLE` | 409 |
| `ERR_OBJECTION_WINDOW_CLOSED` | 409 |
| `ERR_OBJECTION_WINDOW_OPEN` | 409 |
| `ERR_RECORDS_NOT_SCREENED` | 409 |
| `ERR_NO_ELIGIBLE_RECORDS` | 409 |
| `ERR_NOTIFICATIONS_NOT_CLEARED` | 409 |
| `ERR_HEARING_NOT_HELD` | 409 |
| `ERR_MAX_RETRIES_EXCEEDED` | 409 |
| `ERR_WAIVER_NOT_ELIGIBLE` | 409 |
| `ERR_FILING_FEE_UNPAID` | 402 |
