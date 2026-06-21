# Driving School & Behind-The-Wheel API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Driving School & Behind-the-Wheel API, the back-office and portal engine behind a driver-education business. A modern driving school juggles several intertwined obligations at once: it sells multi-track course packages (classroom, online self-study, and behind-the-wheel road instruction), it books scarce instructors and dual-control vehicles into non-overlapping time slots, it tracks how many hours a learner has actually completed against the hours a regulator requires, and it walks each teen or adult learner along a regulated path from prospect, through learner-permit, to a completion certificate accepted by the Department of Motor Vehicles (DMV).

The system exists to make that choreography auditable and consistent. Hours completed must reconcile automatically against a student's readiness for certification; cancellations and refunds must unwind cleanly without stranding money or phantom bookings; and the safety-critical prerequisites for putting a minor behind the wheel — recorded permit, guardian consent, a certified instructor, a dual-control car — must be enforced at the exact moment a lesson is scheduled rather than discovered later. A parent-and-teen portal exposes the same records to the people who depend on them, so the rules that govern who may see and change what are as much a part of the contract as the scheduling math itself.

Because so much of the behavior is time-gated — a lesson can only be completed after it ends, a refund tier depends on how many days have elapsed since activation, a learner's minor status depends on the current date relative to their birthday — the system runs against an explicit server clock that can be advanced for testing. The sections that follow define the global request and response contract, the cross-cutting principles that hold across every workflow, and then the business logic itself.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `SchoolAdmin`, `Instructor`, `Student`, and `Guardian`. When a request is well-authenticated but the acting role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Three of the four roles are tied to a persisted entity, and for those roles `X-User-ID` is an ownership key, not a free-form label. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a student — that student's own enrollments, lessons, certificates, wallet entries, and no-show strikes — compare the resource's student foreign-key field to `X-User-ID`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any lesson compare the lesson's assigned instructor field to `X-User-ID`. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `GuardianConsent` record (the guardian's identity is the consent row itself, whose `guardian_email` names the person); a guardian may act on, and view the portal of, the minor student named by that consent's `student_id`, and ownership checks compare that consent's student linkage to the resource being touched. When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The fourth role, `SchoolAdmin`, is the school operator and is **not** entity-backed. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for audit purposes but does not compare it to any entity's `id`, and a `SchoolAdmin` is never subject to the per-resource ownership check. The `SchoolAdmin` is the broadest actor: it manages packages, students, enrollments, scheduling, no-shows, certification, refunds, and DMV correspondence.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single page returns; when omitted it defaults to 10, and a supplied value must be no less than 1 and no greater than 100. The `offset` parameter is the number of items to skip before the page begins; when omitted it defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order — that is, by `created_at` from oldest to newest.

Each list response carries the pagination bookkeeping inside the `meta` object of the envelope, specifically the `limit`, `offset`, `total_count`, and `has_more` fields.

### 2.4. Common Resource Properties and the Two Entity Tiers

The system distinguishes two tiers of persisted resource. **Full resources** — `Student`, `GuardianConsent`, `Enrollment`, `Instructor`, `Vehicle`, `Lesson`, and `Certificate` — carry the complete set of system-managed fields:

- `id`: a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording first creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification; it is refreshed on every mutation of the resource.
- `version`: a system-managed integer that begins at its initial value of `1` and increments by one with every modification to the resource. It is the basis for optimistic concurrency control described in §2.10.

**Ledger-style resources** — `CoursePackage`, `NoShowStrike`, and `WalletEntry` — are append-style records that are not mutated in place after creation. These carry only `id` and `created_at`; they have no `updated_at` and no `version` field at all. A reader should not expect those two fields on a course package, a no-show strike, or a wallet entry.

Whenever a derived field on a full resource is recomputed — for example a student's hour ledgers or `readiness_score`, or an enrollment's pricing — that recomputation is itself a mutation: it refreshes the owning resource's `updated_at` and increments its `version`.

### 2.5. Resource Resolution and Reference Integrity

Many requests name resources both in the URL path and in the request body. Identifiers are resolved left-to-right in the order they appear, path identifiers first and then body references, and the first identifier that does not resolve to an existing resource causes the whole request to fail with `ERR_NOT_FOUND` before any later reference is examined. A request that schedules a lesson, for instance, validates that the student, the funding enrollment, and any named instructor or vehicle exist before any business rule is evaluated. Read endpoints that fetch a single resource by its path identifier apply the same rule.

The list endpoints double as reverse-lookup tools: a caller can filter no-show strikes, wallet entries, certificates, enrollments, and lessons by the foreign keys that point back to a student, an enrollment, a lesson, an instructor, a vehicle, or a course package, which is how the portal reconstructs a learner's full history without nesting those resources under one another in the URL.

### 2.6. Precision, Rounding, and Monetary Representation

Money in this system is always integer **cents**; there are no fractional cents and no floating-point currency. Every calculation that produces a cent amount — final enrollment price, refund amount, no-show fee, instructor payout — is rounded to a whole cent using the **round half up** convention (a value exactly halfway between two integers rounds upward), and the rounding is applied at the points each calculation in §3 specifies, not repeatedly.

Two non-monetary computed quantities have their own precision. A lesson's `duration_hours` is the elapsed time between its start and end expressed in hours and rounded to two decimal places. A student's `readiness_score` is rounded to four decimal places, again round half up. Hour ledgers accumulate `duration_hours` values and therefore inherit two-decimal granularity.

### 2.7. State Consistency and Cascading Reconciliation

Several operations touch more than one resource. The governing principle is that the system keeps derived state consistent automatically: when a lesson's lifecycle changes, the affected student's hour ledgers, `readiness_score`, `no_show_count`, `wallet_balance_cents`, and milestone `status` are all re-derived as part of the same operation, and the student's `version` advances exactly once for that operation. When an enrollment is cancelled or refunded, the system reaches down and cancels the lessons that depend on it rather than leaving them dangling. These cascades are described in full within the relevant workflows in §3; the rule to hold onto here is that a single client action may legitimately mutate several resources at once, and each mutated full resource has its `updated_at` and `version` advanced as a consequence.

The student milestone ladder is explicitly allowed to move **backward** as well as forward. A student who has reached `ROAD_READY` falls back to `PERMITTED` if a later reversal drops their completed road hours below the required floor; the certificate negotiation with the DMV can likewise loop. These reversions are not error conditions — they are the system honoring the true, recomputed state of the underlying ledgers.

### 2.8. Behind-the-Wheel Safety Prerequisites

Behind-the-wheel (road) instruction is the regulated heart of this system, and the rules guarding it are cross-cutting enough to state once here even though they are exercised inside the scheduling workflow in §3. A `ROAD` lesson may only be booked when, together: the student has a recorded learner permit and stands at the `PERMITTED` or `ROAD_READY` milestone; the assigned instructor is flagged as certified to teach road lessons; and the assigned vehicle has dual-control pedals. A minor student additionally requires a guardian consent that is currently in the `GRANTED` state before any road lesson is scheduled — and the same consent gate applies before that minor's enrollment can be activated. Guardian consent that is later revoked does not retroactively undo road lessons that were already completed; it only blocks the scheduling of new ones.

### 2.9. The Wallet Ledger Principle

Each student has a wallet whose running balance, `wallet_balance_cents`, is the signed sum of that student's wallet entries. Money never appears or disappears outside this ledger: refunds enter as positive credits, no-show fees enter as negative debits, and an operator may post a manual adjustment. A positive `amount_cents` raises the balance and a negative one lowers it; the student's `wallet_balance_cents` is re-derived from the entries rather than stored independently, so the balance and the entries can never disagree.

### 2.10. Optimistic Concurrency Control on Lesson Scheduling

Scheduling a new lesson is the one write in this system that is guarded by optimistic concurrency control against the student it books. The schedule-lesson request must carry `expected_student_version`, a non-optional field whose value is the `version` of the target `Student` as the client last observed it. The server compares that value to the student's current `version`; if another write has advanced the student's version in the meantime — a prior lesson completion that bumped the hour ledgers, a permit recording, or any other mutation — the client's view of the student's remaining road hours and milestone status is stale, and the create is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412). The client must then re-read the student and re-derive the booking before retrying. No other endpoint takes a version field; only lesson scheduling participates in this check.

### 2.11. Validation Ordering

When several checks apply to one endpoint, they are evaluated in a fixed precedence so that the error a caller receives is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED` (401). Then role authorization yields `ERR_FORBIDDEN_ROLE` (403), and for entity-backed roles the ownership check yields `ERR_NOT_RESOURCE_OWNER` (403). Existence of every referenced resource is checked next, left-to-right, yielding `ERR_NOT_FOUND` (404). Only then are state-machine legality (`ERR_INVALID_STATE`, 409) and, where applicable, the lesson-scheduling stale-version check (`ERR_STALE_STUDENT_VERSION`, 412) evaluated. Business-rule checks — guardian consent, road prerequisites, resource availability, interval well-formedness, double-booking, road-hour ceilings, certification readiness — follow after those. The well-formedness of the request body (`ERR_INVALID_REQUEST`, 400) and uniqueness (`ERR_DUPLICATE`, 409) round out the catalogue. The per-endpoint ordering of the business checks, where it matters, is spelled out in §3 alongside the workflow each check guards. A generic business-rule violation that no more specific code covers — for example a refund method requested against a package whose terms make it non-refundable — surfaces as `ERR_VALIDATION` (422).

## 3. Business Logic & Workflows

### 3.1. Course Packages and the Catalogue

Everything a learner buys is a **course package**, created by a `SchoolAdmin`. A package is defined by a unique human-readable `code` (for example a teen full-course code), a display `name`, and a total `price_cents` quoted before any discount. Part of that price is an `enrollment_fee_cents` portion that the school keeps no matter what; this fee must be at least zero and may not exceed the package's `price_cents`, and — important for later — it is **never** refundable. The package also declares how many hours of each track it includes: `included_classroom_hours`, `included_online_hours`, and `included_road_hours`, each a non-negative number. A package that bundles both a classroom track and a road track may carry a flat `bundle_discount_cents` (defaulting to zero, never negative) that is applied at activation only when both of those included-hour figures are above zero. Finally, an `active` flag (defaulting to true) governs whether the package is offered for new enrollments; an inactive package cannot be activated against.

Because a course package is a ledger-style record, it exposes only `id` and `created_at` beyond its business fields, and its `code` must be unique across all packages — a colliding code is rejected with `ERR_DUPLICATE`. Packages can be fetched individually and listed, optionally filtered by their `active` flag, by any role, since learners and guardians need to browse the catalogue.

### 3.2. Registering Learners and the Minor/Guardian Gate

A `SchoolAdmin` registers a learner by supplying their `full_name`, contact `email`, and `date_of_birth`; a `permit_number` may be supplied at registration but is optional and otherwise begins absent. The email must be unique across students, and a duplicate is rejected with `ERR_DUPLICATE`. At registration the server derives `is_minor` by comparing the learner's `date_of_birth` to the current server clock: the learner is a minor when their age is under 18 at that clock. The student is created at the `PROSPECT` milestone, and the system seeds the computed ledgers — `completed_classroom_hours`, `completed_online_hours`, `completed_road_hours`, `scheduled_road_hours`, `readiness_score`, `no_show_count`, and `wallet_balance_cents` — at zero. Students are listable, optionally filtered by their milestone `status`.

A minor cannot be put behind the wheel, nor have an enrollment activated, until a guardian has consented. A guardian consent is created — by a `SchoolAdmin` or by a guardian — against the minor's `student_id`, recording the `guardian_name`, the `guardian_email`, and the `relationship`, which is either `PARENT` or `LEGAL_GUARDIAN`. A new consent begins in the `PENDING` state. The named guardian grants it, moving it from `PENDING` to `GRANTED`; this transition is legal only while the consent sits at `PENDING`, and an attempt from any other state is rejected with `ERR_INVALID_STATE`. A granted consent may later be revoked, moving it from `GRANTED` to `REVOKED`, again legal only from `GRANTED`. `REVOKED` is terminal. As noted in §2.8, revocation blocks new road scheduling for the minor but leaves already-completed lessons intact. Each grant or revoke advances the consent's `version`.

Consents are listable and filterable by `student_id` and by `status`, which is how the portal answers "does this minor have a live consent?" — the gate for activation and road scheduling is satisfied only by a consent whose `status` is `GRANTED`.

### 3.3. The Student Milestone Ladder

A student's `status` walks a regulated ladder: `PROSPECT`, then `ENROLLED`, then `PERMITTED`, then `ROAD_READY`, then `CERTIFIED`, and finally `LICENSED`. The first hop is automatic: when a student still sitting at `PROSPECT` has an enrollment activated, the system bubbles them from `PROSPECT` to `ENROLLED` as part of that activation.

Recording a learner permit is a `SchoolAdmin` action that supplies a non-empty `permit_number` and advances the student from `ENROLLED` to `PERMITTED`. It is legal only while the student is at `ENROLLED`; from any other milestone it is rejected with `ERR_INVALID_STATE`, and a missing or empty permit number is a malformed request. Recording the permit sets `permit_number` on the student and bumps the student's `version`.

The hop from `PERMITTED` to `ROAD_READY` is automatic and earned through road hours: when completing a road lesson brings the student's `completed_road_hours` to at least the required road-hour floor of 6 hours, and the student is sitting at `PERMITTED`, the system bubbles them to `ROAD_READY`. This hop can also be undone: if a previously completed road lesson is reversed and the student's `completed_road_hours` falls below that 6-hour floor while they are at `ROAD_READY`, the system regresses them back to `PERMITTED`. Both the forward earn and the backward regression advance the student's `version`.

Issuing a certificate, a `SchoolAdmin` action covered in §3.7, moves a `ROAD_READY` student to `CERTIFIED`. The final hop, `CERTIFIED` to `LICENSED`, is automatic: it fires when the student's certificate is accepted by the DMV. `LICENSED` is the terminal milestone.

### 3.4. Enrolling and Activating: Discount Stacking

Enrollment binds a student to a package. A `SchoolAdmin` first creates an enrollment in the `DRAFT` state by naming the `student_id` and the `package_id`, optionally attaching a `promo_code`. A draft carries the computed fields `final_price_cents`, `amount_paid_cents`, `refunded_cents` (all starting at zero), `refund_method` and `activated_at` (both absent until set), and a lifecycle `status`.

Activation, a `SchoolAdmin` action, drives the enrollment from `DRAFT` to `ACTIVE` and is the moment money is reckoned. Activation is legal only from `DRAFT`; it requires the chosen course package to be `active`, an inactive package being rejected with `ERR_VALIDATION`; and if the enrolling student is a minor it requires a `GRANTED` guardian consent for that student, the absence of which is rejected with `ERR_GUARDIAN_CONSENT_REQUIRED`. On success the system computes the net charge into `final_price_cents` by stacking discounts in a strictly pinned order against a running subtotal that begins at the package's `price_cents`:

1. **Teen discount, applied first.** If the student is a minor, the running subtotal is multiplied by one minus the teen discount rate of ten percent — that is, reduced to ninety percent of its current value.
2. **Promo percentage, applied second.** If the enrollment's `promo_code` is the value `FLAT10`, the running subtotal is then multiplied by one minus the promo rate of ten percent — reduced to ninety percent of whatever it is after step 1.
3. **Bundle flat discount, applied last.** If — and only if — the package includes both tracks, meaning both its `included_classroom_hours` and its `included_road_hours` are greater than zero, the package's `bundle_discount_cents` is subtracted from the running subtotal.

After all three steps, the subtotal is rounded to a whole cent using round half up exactly once, and then floored at zero so the price can never go negative; the result is `final_price_cents`. The percentage steps multiply and the flat step subtracts, in that fixed sequence — for a minor on a both-tracks package with the `FLAT10` code, all three apply in order; for an adult with no promo on the same package, only the bundle flat applies and both percentage steps are skipped. Activation then sets `amount_paid_cents` equal to `final_price_cents` (the student is recorded as having paid the charged amount; activation does not itself post a wallet entry), stamps `activated_at` with the current clock as the baseline for any future schedule-tier refund, sets the status to `ACTIVE`, bubbles a `PROSPECT` student to `ENROLLED` as described in §3.3, and advances the enrollment's `version`.

Enrollments may be fetched and listed, with list filtering by `student_id`, `package_id`, and `status`, available to the admin and to the student and guardian who own the record.

### 3.5. Completing, Cancelling, and Refunding an Enrollment

An active enrollment ends in one of three terminal ways. **Completion**, a `SchoolAdmin` action, moves the enrollment from `ACTIVE` to `COMPLETED`; it is legal only from `ACTIVE` and only when the student is linked to a certificate for this enrollment that is in `ISSUED`, `SUBMITTED`, or `ACCEPTED` status — there must be a real certificate before an enrollment can be closed out. Completion advances the enrollment's `version`.

**Cancellation**, a `SchoolAdmin` action, moves the enrollment from `ACTIVE` to `CANCELLED`. It is a clean teardown allowed only while no lesson under the enrollment has been completed — compensation is only valid before any hours have been consumed — and an attempt while a completed lesson exists is rejected with `ERR_INVALID_STATE`. As part of cancellation, every still-`SCHEDULED` lesson under the enrollment is cascade-cancelled (each moving from `SCHEDULED` to `CANCELLED`), and each cancelled road lesson releases its `duration_hours` back out of the student's `scheduled_road_hours`. No money moves on a cancellation, because by definition no lessons were consumed. The enrollment's `version` advances.

**Refund**, a `SchoolAdmin` action, moves the enrollment from `ACTIVE` to `REFUNDED`. The request supplies two fields that live with this operation: a `refund_method`, which must be either `PRO_RATA` or `SCHEDULE_TIER`, and a `refund_destination`, which must be `WALLET`. Refund is legal only from `ACTIVE`. Like cancellation, it first cascade-cancels every still-`SCHEDULED` lesson under the enrollment, each road lesson releasing its hours back from `scheduled_road_hours`. It then computes the refund amount (see below), records the chosen `refund_method` and the resulting `refunded_cents` on the enrollment, and posts a wallet credit — a wallet entry against the student for a positive `amount_cents` equal to `refunded_cents`, with `reason` `REFUND_CREDIT` and the originating `enrollment_id` — which raises the student's `wallet_balance_cents`. The enrollment then sits at `REFUNDED` with its `version` advanced.

The refund amount itself is computed two different ways depending on the method chosen, and the same enrollment can yield two different figures. In both methods the refundable base is the enrollment's `final_price_cents` minus the package's `enrollment_fee_cents`, since the enrollment fee is never returned, itself clamped to zero if that subtraction would go negative. Under **`PRO_RATA`**, the refund is forward-looking on unused road hours and ignores elapsed time: the consumed hours are the student's `completed_road_hours` of road instruction under this enrollment, the remaining hours are the package's `included_road_hours` minus those consumed (clamped to zero if that would go negative), and the refund is the refundable base multiplied by the ratio of remaining hours to the package's `included_road_hours`, rounded to a whole cent half up; when the package's `included_road_hours` is zero the ratio is taken to be zero and the refund is zero. Under **`SCHEDULE_TIER`**, the refund is tiered on calendar time since activation and ignores hours consumed: take the whole number of elapsed days, computed by flooring the gap between the current clock and the enrollment's `activated_at` to whole days; if that is at most 3 days the refund percentage is one hundred percent, otherwise if at most 14 days it is seventy-five percent, otherwise if at most 30 days it is fifty percent, and beyond 30 days it is zero percent; the refund is the refundable base multiplied by that percentage, rounded to a whole cent half up.

### 3.6. Scheduling a Lesson: The Full Validation Chain

Scheduling a lesson is the most heavily guarded write in the system, performed by a `SchoolAdmin`. The request names the `student_id` attending, the `enrollment_id` funding the hours, the `lesson_type` (one of `CLASSROOM`, `ONLINE`, or `ROAD`), the `start_at` and `end_at` instants, the carried `expected_student_version` for the concurrency check, and — depending on track — an `instructor_id` and a `vehicle_id`. A new lesson is created in `SCHEDULED` status with its `duration_hours` derived as the elapsed time from `start_at` to `end_at` in hours rounded to two decimals; the interval is treated as half-open, covering `start_at` up to but not including `end_at`. For a road lesson, that `duration_hours` is added to the student's `scheduled_road_hours` at creation. Scheduling advances the student's `version`.

The checks run in a defined order. After the resource-existence resolution of §2.5, the stale-version guard of §2.10 fires: `expected_student_version` must match the student's live `version`, or the create is rejected with `ERR_STALE_STUDENT_VERSION`. A minor with no `GRANTED` guardian consent cannot have a road lesson booked and is rejected with `ERR_GUARDIAN_CONSENT_REQUIRED`. The road prerequisite bundle is then enforced: a `ROAD` lesson requires the student to be at `PERMITTED` or `ROAD_READY` (a recorded permit), the assigned instructor to be `certified_road`, and the assigned vehicle to be `dual_control`; any of these missing yields `ERR_ROAD_PREREQUISITE_NOT_MET`. Referential availability is checked next: the assigned instructor must be `active`, the vehicle must not be `out_of_service`, and the funding enrollment must be `ACTIVE`; a violation yields `ERR_RESOURCE_UNAVAILABLE`. The interval must be well-formed — `end_at` strictly after `start_at`, and `start_at` strictly in the future relative to the current clock — or the request is rejected with `ERR_INVALID_INTERVAL`.

Two double-booking checks then protect the shared resources. The assigned instructor must have no other `SCHEDULED` lesson whose half-open interval overlaps this one; back-to-back adjacency where one lesson's end exactly meets the next lesson's start is allowed, but any true overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`. For a road lesson the assigned vehicle must likewise be free, but the vehicle's window is padded: an existing booking's interval is expanded by that vehicle's `prep_buffer_minutes` of mandatory cleaning-and-fueling time **after** its end, and if that padded window overlaps the new lesson's interval the request is rejected with `ERR_VEHICLE_DOUBLE_BOOKED`. Finally, a road-hour ceiling: scheduling a road lesson must not push the student's `scheduled_road_hours` plus `completed_road_hours` above the funding package's `included_road_hours`, or the request is rejected with `ERR_ROAD_HOURS_EXCEEDED`.

An instructor is required for classroom and road lessons; a vehicle is required only for road lessons; a request that omits a required `instructor_id` or `vehicle_id` for the lesson type is rejected with `ERR_INVALID_REQUEST`. The schedulable resources are themselves created by a `SchoolAdmin`: an instructor is registered with a `full_name`, a unique `email`, an `hourly_rate_cents` pay rate, a `certified_road` flag (defaulting to false) that gates road teaching, and an `active` flag (defaulting to true); a vehicle is registered with a unique `plate`, a `dual_control` flag (defaulting to false) that gates road use, a `prep_buffer_minutes` turnaround buffer (defaulting to zero), and an `out_of_service` flag (defaulting to false). A colliding instructor `email` or vehicle `plate` is rejected with `ERR_DUPLICATE`. Instructors are listable, optionally filtered by their `active` flag, and vehicles are listable, optionally filtered by their `out_of_service` flag. Lessons can be fetched and listed, with list filtering by `student_id`, `enrollment_id`, `instructor_id`, `vehicle_id`, `status`, and `lesson_type`.

### 3.7. Completing a Lesson and Reconciling Readiness

An `Instructor` completes a lesson once it is over. Completion moves the lesson from `SCHEDULED` to `COMPLETED` and is legal only from `SCHEDULED` and only once the current clock has reached or passed the lesson's `end_at`; an early attempt is an invalid-state rejection. On completion the system adds the lesson's `duration_hours` into the matching ledger — `completed_classroom_hours`, `completed_online_hours`, or `completed_road_hours` according to `lesson_type` — and for a road lesson it also subtracts that `duration_hours` from `scheduled_road_hours`, since the scheduled hour has now been consumed rather than merely reserved. It computes the lesson's `instructor_payout_cents`, recomputes the student's `readiness_score`, and, when this is a road lesson that brings `completed_road_hours` to at least the 6-hour floor and the student is at `PERMITTED`, bubbles the student to `ROAD_READY`. The student's `version` advances once for the whole operation.

The instructor's pay for a single completed lesson is the instructor's `hourly_rate_cents` multiplied by the lesson's `duration_hours`, rounded to a whole cent half up; this per-lesson figure is stored on the lesson as `instructor_payout_cents`. This per-line rounding matters because the period payout summary, described in §3.10, sums these already-rounded per-lesson amounts rather than re-deriving from total hours.

A student's `readiness_score` is a weighted measure of how completely the three required-hour floors have been met, recomputed on every lesson completion and checked again at certificate issuance. For each track, take the ratio of completed hours to that track's required floor but cap it at 1.0 — road against a floor of 6 hours, classroom against a floor of 30 hours, online against a floor of 8 hours. The score is the road ratio weighted at 0.5, plus the classroom ratio weighted at 0.3, plus the online ratio weighted at 0.2, with the sum rounded to four decimal places half up. Because the weights total exactly 1.0 and each ratio is capped at 1.0, the score reaches exactly 1.0 if and only if all three floors are fully met, which is the precise gate for certification.

Issuing the completion certificate is a `SchoolAdmin` action naming the `enrollment_id` whose hours satisfied the requirement. It is legal only when the student is at `ROAD_READY` and their `readiness_score` equals exactly 1.0; the `ROAD_READY` state is checked first, so a student not at `ROAD_READY` is an invalid-state rejection, and only then is a readiness below 1.0 rejected with `ERR_READINESS_NOT_MET`. On issuance the student advances from `ROAD_READY` to `CERTIFIED`, a `Certificate` is created in the `ISSUED` state recording its `student_id` and `enrollment_id`, the student's current `readiness_score` is snapshotted into the certificate's `readiness_score_at_issue` (which must be 1.0), the certificate's `dmv_reference` begins absent until submission, and the student's `version` advances.

### 3.8. No-Shows and Escalating Strikes

When a learner fails to appear, a `SchoolAdmin` marks the lesson a no-show. This moves the lesson from `SCHEDULED` to `NO_SHOW`, legal only from `SCHEDULED` and only once the current clock has reached or passed the lesson's `start_at`. Marking a no-show creates a `NoShowStrike` against the student, recording its `student_id` and the missed `lesson_id`, and stamping its `strike_index` as the student's running `no_show_count` plus one — that is, the 1-based chronological ordinal of this strike for the student, ordered by the strike's `created_at`. Because strikes are minted one per request, two strikes can never share an index.

The strike carries a `fee_charged_cents` determined by its `strike_index` on an escalating schedule: the first strike is forgiven and charges nothing; the second strike charges the base no-show fee of 4000 cents (forty dollars); the third and every subsequent strike charges double that base — 8000 cents. Whenever the charged fee is above zero, the system posts a wallet debit: a wallet entry against the student for a negative `amount_cents` equal to that fee, with `reason` `NO_SHOW_DEBIT` and the `enrollment_id` carried over from the missed lesson, which lowers the student's `wallet_balance_cents`. For a road no-show, the lesson's `duration_hours` is subtracted back out of `scheduled_road_hours`, since the reserved hour was forfeited rather than consumed. The student's `no_show_count` is then re-derived and the student's `version` advances. No-show strikes can be fetched and listed, filterable by `student_id` and `lesson_id`.

### 3.9. Cancelling a Lesson

A `Student` may cancel their own scheduled lesson, but only outside the cancellation cutoff window. The cancellation moves the lesson from `SCHEDULED` to `CANCELLED`, is legal only from `SCHEDULED`, and is permitted only when the current clock is strictly earlier than the lesson's `start_at` minus the cancellation cutoff lead time of 24 hours; in other words, once the clock reaches the point one cutoff-window's-worth of time before the lesson begins, the student can no longer cancel and the attempt is rejected as an invalid state. A cancelled road lesson releases its `duration_hours` back out of `scheduled_road_hours`, returning those hours to the enrollment. The student's `version` advances. This learner-initiated cancellation is distinct from the cascade cancellations triggered by enrollment teardown in §3.5, which the admin drives; if a reversal of an already-completed road lesson were ever to drop completed road hours below the floor, the milestone regression of §3.3 would apply, but the student cancel path itself only ever touches a `SCHEDULED` lesson.

### 3.10. The DMV Handoff and Instructor Payout Summary

Once a certificate exists, a `SchoolAdmin` submits it to the DMV. Submission moves the certificate from `ISSUED` to `SUBMITTED` and mints its `dmv_reference`. The DMV's decision is then recorded through a callback carrying an `outcome`: an `ACCEPTED` outcome moves the certificate from `SUBMITTED` to `ACCEPTED` and bubbles the student from `CERTIFIED` to `LICENSED`, while a `REJECTED` outcome moves it from `SUBMITTED` to `REJECTED`. Submission is legal from `ISSUED` and from `REJECTED`, and recording a decision is legal only from `SUBMITTED`; any other starting state is an invalid-state rejection. A rejected certificate is not dead: it can be resubmitted, moving from `REJECTED` back to `SUBMITTED` and re-minting its `dmv_reference`, which reopens the `SUBMITTED → REJECTED → SUBMITTED` negotiation loop with the DMV. `ACCEPTED` is the terminal certificate state. Each submit, callback, and resubmit advances the certificate's `version`. Certificates can be fetched and listed, filterable by `student_id`, `enrollment_id`, and `status`.

The school settles instructor pay through a computed payout summary, available to the admin and to the instructor themselves, that takes a `period_start` and a `period_end` (both required query parameters, their absence rejected with `ERR_INVALID_REQUEST`) and reports a `period_total_cents` together with a `lesson_count`. The period is half-open over the lessons it sums, anchored on each lesson's `start_at`: a lesson contributes when its `start_at` satisfies `period_start <= start_at < period_end`. The total is built by the round-per-line-then-sum rule: for every `COMPLETED` lesson whose `start_at` falls in the period, take that lesson's already-rounded `instructor_payout_cents` and add them up — the system does not multiply the rate by total hours and round once at the end. The `lesson_count` is simply how many completed lessons contributed.

Beyond refunds and no-show debits, a `SchoolAdmin` may post a manual wallet adjustment directly, supplying a `student_id`, a signed `amount_cents`, a `reason` (here `ADMIN_ADJUSTMENT`, alongside the system-posted `REFUND_CREDIT` and `NO_SHOW_DEBIT` reasons), and an optional `enrollment_id`; posting the entry re-derives the student's `wallet_balance_cents`. Wallet entries can be fetched and listed, filterable by `student_id`, `enrollment_id`, and `reason`.

### 3.11. Driving the Clock

Because nearly every temporal rule in this system — whether a lesson may be completed, which refund tier applies, whether a learner counts as a minor — is measured against the server's notion of "now," an admin-only test-driving capability sets the server's current UTC clock to a supplied `to_iso8601` instant. Every subsequent age derivation, completion-window check, cancellation-cutoff check, and refund-tier computation reads from that clock until it is set again.

## 4. Endpoint Definitions

Operations that create a brand-new, independently addressable resource return a `201 Created` status code; operations that modify or transition an existing resource, and computed read operations, return a `200 OK` status code. All read (GET) endpoints return `200 OK`. The request and response payloads for each endpoint are not repeated here — the field-level contract for every operation is given in the §3 narrative that governs it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/course-packages` | Create a course package | SchoolAdmin |
| GET | `/course-packages/{id}` | Fetch a course package | SchoolAdmin, Student, Guardian, Instructor |
| GET | `/course-packages` | List course packages | SchoolAdmin, Student, Guardian, Instructor |
| POST | `/students` | Register a student | SchoolAdmin |
| GET | `/students/{id}` | Fetch a student with computed ledgers and readiness | SchoolAdmin, Student, Guardian, Instructor |
| GET | `/students` | List students | SchoolAdmin |
| POST | `/students/{id}/record-permit` | Record a DMV learner permit | SchoolAdmin |
| POST | `/students/{id}/certificate` | Issue a completion certificate | SchoolAdmin |
| POST | `/guardian-consents` | Create a pending guardian consent | SchoolAdmin, Guardian |
| GET | `/guardian-consents/{id}` | Fetch a guardian consent | SchoolAdmin, Guardian |
| GET | `/guardian-consents` | List/filter guardian consents | SchoolAdmin, Guardian |
| POST | `/guardian-consents/{id}/grant` | Guardian grants consent | Guardian |
| POST | `/guardian-consents/{id}/revoke` | Guardian revokes consent | Guardian |
| POST | `/enrollments` | Create a draft enrollment | SchoolAdmin |
| GET | `/enrollments/{id}` | Fetch an enrollment | SchoolAdmin, Student, Guardian |
| GET | `/enrollments` | List/filter enrollments | SchoolAdmin, Student, Guardian |
| POST | `/enrollments/{id}/activate` | Activate enrollment and compute final price | SchoolAdmin |
| POST | `/enrollments/{id}/complete` | Close out a certified enrollment | SchoolAdmin |
| POST | `/enrollments/{id}/cancel` | Cancel a pre-completion enrollment | SchoolAdmin |
| POST | `/enrollments/{id}/refund` | Refund an enrollment to wallet | SchoolAdmin |
| POST | `/instructors` | Create an instructor | SchoolAdmin |
| GET | `/instructors/{id}` | Fetch an instructor | SchoolAdmin, Instructor |
| GET | `/instructors` | List instructors | SchoolAdmin |
| GET | `/instructors/{id}/payout-summary` | Computed instructor payout over a period | SchoolAdmin, Instructor |
| POST | `/vehicles` | Create a vehicle | SchoolAdmin |
| GET | `/vehicles/{id}` | Fetch a vehicle | SchoolAdmin, Instructor |
| GET | `/vehicles` | List vehicles | SchoolAdmin |
| POST | `/lessons` | Schedule a lesson | SchoolAdmin |
| GET | `/lessons/{id}` | Fetch a lesson | SchoolAdmin, Student, Instructor, Guardian |
| GET | `/lessons` | List/filter lessons | SchoolAdmin, Student, Instructor, Guardian |
| POST | `/lessons/{id}/complete` | Complete a lesson after its end | Instructor |
| POST | `/lessons/{id}/no-show` | Mark a lesson no-show | SchoolAdmin |
| POST | `/lessons/{id}/cancel` | Student cancels a lesson outside the cutoff | Student |
| GET | `/no-show-strikes/{id}` | Fetch a no-show strike | SchoolAdmin, Student, Guardian |
| GET | `/no-show-strikes` | List/filter no-show strikes | SchoolAdmin, Student, Guardian |
| GET | `/wallet-entries/{id}` | Fetch a wallet entry | SchoolAdmin, Student, Guardian |
| GET | `/wallet-entries` | List/filter wallet entries | SchoolAdmin, Student, Guardian |
| POST | `/wallet-entries` | Admin wallet adjustment | SchoolAdmin |
| GET | `/certificates/{id}` | Fetch a certificate | SchoolAdmin, Student, Guardian |
| GET | `/certificates` | List/filter certificates | SchoolAdmin, Student, Guardian |
| POST | `/certificates/{id}/submit` | Submit certificate to DMV | SchoolAdmin |
| POST | `/certificates/{id}/dmv-callback` | Record DMV decision | SchoolAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the server clock | SchoolAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_STUDENT_VERSION` | 412 |
| `ERR_GUARDIAN_CONSENT_REQUIRED` | 422 |
| `ERR_ROAD_PREREQUISITE_NOT_MET` | 422 |
| `ERR_RESOURCE_UNAVAILABLE` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 |
| `ERR_ROAD_HOURS_EXCEEDED` | 422 |
| `ERR_READINESS_NOT_MET` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE` | 409 |
| `ERR_VALIDATION` | 422 |
