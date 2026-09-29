# Worklog — task_2248_vacation_ownership_sales_tour_rescission

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2248_vacation_ownership_sales_tour_rescission/` and `tasks/task_2248_vacation_ownership_sales_tour_rescission/workspace/`.

## Step 2: Scaffold artifacts complete — 2026-09-01

- `SCAFFOLD.yaml` (§1.0–§1.7): 14 entities, 10 state machines, 3 concurrency rules, 15 calculations, 37 validations, 59 endpoints, 55 errors, 6 roles; difficulty_level `expert_plus`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rule blocks / 27 instances (3 per rule).
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): all 9 sections, 95 instances (62 with `test_recipe`, 33 `excluded_because` stubs).
- `scaffold_lint.py`: clean lint (1376 calls scanned). Every one of the 55 catalog error ids is referenced by at least one §1.8/§1.9 instance.

Verbatim subagent summary:

> All three scaffold artifacts are complete and lint-clean. No sibling task directory was read at any point — the design is derived solely from the scenario text and the generator skill's own spec.
>
> **`SCAFFOLD.yaml`** (§1.0–§1.7, 3141 lines; keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no design keys)
> - **14 entities**: TourChannel, Prospect, SalesGallery, SalesRepresentative, TourBooking, SalesPresentation, DisclosureAcknowledgment, ProhibitedClaimFinding, PurchaseAgreement, FinancingApplication, RescissionRequest, RefundDisbursement, ClosingPackage, ComplianceRetrainingAssignment
> - **10 state machines** (parallel shape): TourBooking, SalesPresentation, PurchaseAgreement (dual axes: rescission_status × fulfillment_status), FinancingApplication, RescissionRequest, ClosingPackage, ComplianceRetrainingAssignment, TourChannel, SalesGallery, SalesRepresentative
> - **3 concurrency rules** (OCC): `expected_agreement_version` on `POST /financing-applications`, `expected_presentation_version` on `POST /prohibited-claim-findings`, `expected_representative_version` on `POST /retraining-assignments`
> - **15 calculations**, incl. `tour_qualification_evaluation` (cap-before-penalty step order), `rescission_deadline` (per-state anchor variant + weekend/federal-holiday roll), `refund_settlement` (STATUTORY_FULL vs CONTRACTUAL_NET_OF_GIFT), `financing_underwriting` (FICO tier → APR/LTV cap), `representative_cancellation_rate` (90-day window, min sample), `trade_in_equity_credit`, `gift_liability_ledger`, `gallery_slot_occupancy_ledger`
> - **37 validations** on a single strict priority ladder (401 → 403 → 400 → 404 path → 404 body-FK → representative identity → 412 OCC → 409 state → domain 409s → segregation of duties → 422 business rules)
> - **59 endpoints** (incl. `POST /_ops/rescission-sweep` and `POST /_clock/set_current_utc`), **55 errors**, **6 roles** (MarketingManager, GalleryManager, SalesRepresentative, ComplianceOfficer, ContractAdministrator, PlatformAdmin) with `segregation_of_duties` role model, `immediate` consistency, archetypes compliance_audit + temporal_windowing, difficulty `expert_plus`.
>
> **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8): all 9 difficulty rules, **3 instances each = 27**, every one with a full `setup_api_calls`/`trigger`/`assert` recipe and pre-computed cent-level literals.
>
> **`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9): all 9 required sections, **95 instances — 62 real test recipes + 33 `excluded_because` stubs** (entities 12/0, state_machines 11/7, calculations 12/9, validations 8/9, endpoints 5/4, errors 5/0, rbac 5/0, cross_cutting_complexity_layers 3/4, consistency_model 1/0).
>
> Verification performed
> - `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (59 endpoints, 14 entities, 27 §1.8 + 62 §1.9 instances, **1376 calls scanned**).
> - Names unique across the union of both design files; zero overlap between §1.8 and §1.9 names; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name.
> - Error-catalog coverage: all **55** catalog ids are referenced by at least one design instance (the only unmatched `ERR_XXX` is the response-envelope illustration on SCAFFOLD.yaml line 55).

## Step 3: Copy shared files — 2026-09-01

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01

PRD generated and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — 503 lines (504 incl. trailing newline), ends at §5 with no audit footer.

**Structure**
- §1 Introduction — 3 paragraphs (domain framing, scope, the two design commitments: hard compliance gates + exact escrow conservation).
- §2 Global Specifications — 11 subsections: 2.1 Identity/RBAC (6 roles, `SalesRepresentative` entity-backed vs. 5 opaque), 2.2 Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning (incl. the two event entities carrying only `id`+`created_at`), 2.5 Logical Clock, 2.6 Numeric Precision, 2.7 Jurisdictional Rescission Rules + federal-holiday calendar, 2.8 Stale-Version Guards, 2.9 Validation Precedence (1–37 explicit), 2.10 Cascades/Derived Counters/Posture, 2.11 Segregation of Duties.
- §3 Business Logic — 9 subsections following the sales motion (channels/no-show probation → galleries & roster → qualification scoring → booking/reschedule → check-in & rotation → presentation compliance → agreement execution & financials → financing/funding/closing → rescission intake/refunds/retraining).
- §4 — 4-column table, 59 endpoints, preceded by the status-code paragraph.
- §5 — 2-column table, 55 error codes.

**Contract 1 — Field-Name Coverage: PASS.** 169/169 distinct scaffold field and request/query/path/computed-output identifiers appear in backticks; 0 missing.

**Contract 2 — Rule Coverage: PASS.** 37/37 validations with explicit priority ordering; 3/3 OCC guards framed purely as stale-version; 53/53 state transitions across all 10 machines; 15/15 calculations with pinned rounding order; all 55 error IDs catalogued with matching HTTP statuses (0 mismatches); all 59 endpoints' role sets verified (0 mismatches); entity enums/ranges/defaults surfaced; sibling-branch symmetry stated on both sides.

**Contract 3 — §3 Path Purity: PASS.** 331 distinct backtick tokens in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos.

**Additional checks:** no pseudocode operators, no `min(`/`max(`/`round(` call syntax, no fuzzy quantifiers. Six embedded worked examples verified numerically (qualification cap-then-penalty 110→70, trade-in 1022391 vs. 1022392, LTV cap 3172981/3005982 and payment 41583, capacity adjacency at 11:30 vs. 11:29, rep exclusivity at 11:45 vs. 11:46, refund 320000→287600).

## Step 5: Generate unit tests — 2026-09-01

The suite for task 2248 is complete.

## Files written

**Infrastructure — `test_helpers/`** (10 files): `__init__.py`, `api_client.py`, `api_errors.py`, `factories.py`, `fixtures.py`, `assertions.py`, `constants.py`, `test_users.py`, `types.py`.

**Test cases — `test_suite/`**: `conftest.py` plus 18 modules, **116 tests**.

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty §1.8) | `test_01`…`test_09` | 54 |
| B (Corner §1.9) | `test_10_entity_shapes` (12), `test_11_state_machines` (11), `test_12_calculations` (12), `test_13_validations` (8), `test_14_endpoints` (5), `test_15_errors` (5), `test_16_rbac` (5), `test_17_cross_cutting` (3), `test_18_consistency` (1) | 62 |

## Coverage

- **Queue A: 27/27 difficulty instances, ≥2 tests each** (no difficulty stubs exist).
- **Queue B: 62/62 non-stub corner instances, exactly 1 test each.** The 33 `excluded_because:` stubs were not translated, and no test tags a stub.
- **Instances skipped for the PRD-first filter: none.** Every live instance had verbatim PRD coverage that uniquely derives its outcome.

## Audits (all clean)

`ast`-based audit over the whole suite: exactly one `Design:` line per test, always the final docstring line, every tag resolving to a real instance name; no docstring mentions "scaffold"; every quoted span ≥25 chars re-greps verbatim into the whitespace-normalized `workspace/PRD.md`. Result: `problems: 0`. `pytest --collect-only` collects 116 tests with no import errors; `pyflakes` is clean. The implementation directory and all sibling task directories were never read; no test has been executed against a server.

## Three design assertions overridden by the PRD (design yaml was wrong; PRD governs)

1. `validations/rotation_position_uniqueness_scoped_to_one_gallery` asserted `cancellation_rate == null`; PRD §3.2 says a new representative starts at `0.0000`, so the test asserts `0.0`.
2. `validations/retraining_module_count_gate_applies_only_to_complete` asserted `modules_completed == null` and a success state of `COMPLETE`; the PRD opens an assignment at `modules_completed` 0 and names the terminal state `COMPLETED`.
3. `validations/gallery_posture_gate_reevaluated_at_every_downstream_step` triggered `set-status {"status": "RESTRICTED"}`, which the PRD forbids (only `OPEN` or `CLOSED` may be supplied). The test instead reaches `RESTRICTED` legitimately — assigning and starting retraining on the gallery's only representative drives `available_rep_count` to 0 — then `CLOSED`, then re-derives back to `OPEN`, which also exercises the "requesting `OPEN` from `CLOSED` re-derives rather than obeys" rule.

## Step 6: Generate implementation — 2026-09-01

Implementation is complete and verified.

## Files written

All under `workspace/implementation/` (~3,130 lines of Python):

- `start.sh` — `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded `pip install -q -r requirements.txt`, then `exec python3 app.py`. Honors `PORT` (default 10000), binds `0.0.0.0`.
- `requirements.txt`, `app.py` (app factory, blueprint registration, envelope-shaped error handlers for `ApiError`/`HTTPException`/unhandled, `GET /healthz`)
- `store.py` (in-memory dict store, logical clock epoch 2026-08-01T00:00:00Z, `_seq` ordering), `envelope.py` (meta/response_type/data, per-request version bumping via a dirty set), `errors.py` (55 error specs), `auth.py` (X-User-ID / X-User-Role, 6 roles), `validators.py`, `calc.py` (all pinned money/score/deadline math with `Decimal` + ROUND_HALF_UP), `derive.py` (derived fields and cascades), `helpers.py` (lookups, filtering, pagination)
- `routes/` — `__init__.py` plus `channels`, `galleries`, `prospects`, `bookings`, `presentations`, `agreements`, `financing`, `rescission`, `closing`, `retraining`, `ops`

## Endpoints

59 PRD endpoints plus `GET /healthz`, covering tour channels, sales galleries, sales representatives, prospects, tour bookings, sales presentations, disclosure acknowledgments, prohibited claim findings, purchase agreements, financing applications, rescission requests, refund disbursements, closing packages, retraining assignments, and the ops hooks `POST /_clock/set_current_utc` and `POST /_ops/rescission-sweep`.

## Storage

Process-memory dicts only — no SQLite, no disk JSON, no `/tmp` cache, no seeding or hardcoded entities. A cold boot returns `total_count: 0` for every collection.

## Verification

Server boots cleanly from a fresh process (`bash start.sh` → `{"status":"ok"}` on `/healthz`, verified on five separate ports including a final cold boot returning an empty booking list). Three throwaway smoke suites in `/tmp` (~250 assertions total) all report `FAILURES: 0`. Covered: envelope/meta shape and 401/403/400/404/409/412/422 precedence per PRD §2.9; pinned worked examples (`trade_in_equity_credit_cents` 1022391, financials 2880000/10080/139980/3019980 and 2205000/7718/2342618, `ltv_cap_cents` 3172981 and 2328856, `monthly_payment_cents` 41583, refund fork 287600/32400, NV deadline `2026-08-06T23:59:59.999Z`); capacity adjacency and rep exclusivity boundaries; gift-liability accrual and compensation; disclosure progression and compliance scoring 70/60/85/100; auto-flag, strike accumulation to SUSPENDED with cascade retraining assignment and gallery RESTRICTED re-derivation; separation of duties on review and refunds; timely/untimely and POSTMARK-basis rescission with EXPIRED → RESCINDED; funding, closing package recording/delivery, prospect owner flip; clock monotonicity and the rescission sweep.

## Step 7: Run tests and iterate — 2026-09-01

All 8 parallel rounds green (116/116 each) for two consecutive sweeps.

## Summary

**Iterations run:** 3 sweeps of 8 parallel rounds (iteration 1: 112/116 in all 8; iteration 2: 116/116 in all 8; iteration 3, after flake hardening: 116/116 in all 8).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable — the failures were test-side mis-translations of PRD §2.9's numbered validation precedence, plus one load-induced transport flake.

**Fixes applied to `test_suite/`** (3 tests, all STEP 2 "TEST IS WRONG" — assertion mis-translation, fixed toward PRD):

- `test_14_endpoints.py::test_the_acknowledgment_projection_never_leaks_a_sibling_presentation` — asserted `disclosure_status == "PENDING"` after one required acknowledgment. PRD §3.6: *"The dimension advances `PENDING → PARTIAL` whenever the count is above 0 but still below `required_disclosure_count`."* With `disclosure_ack_count == 1` (asserted in the same test) the PRD-faithful value is `PARTIAL`.
- `test_11_state_machines.py::test_completion_needs_all_three_disclosures_and_a_review_that_has_happened` — expected `ERR_DISCLOSURES_INCOMPLETE` on a `complete` call where `review_status` was *also* still `UNREVIEWED`. PRD §2.9 pins priority 8 (`ERR_INVALID_PRESENTATION_STATE`) ahead of priority 16 (`ERR_DISCLOSURES_INCOMPLETE`) and states *"Where several checks could fire on one request, the earlier one always wins."* Resequenced the test so both errors are still exercised, each in the state where PRD makes it the first failing check: unreviewed+partial → `ERR_INVALID_PRESENTATION_STATE`, then `CLEAR` the review (score 90, no `EGREGIOUS`) → `ERR_DISCLOSURES_INCOMPLETE`, then the third ack → success + booking `TOURED`. No assertion was dropped; two were added (`PARTIAL`, `compliance_score == 90`).
- `test_11_state_machines.py::test_the_refund_can_be_created_and_settled_only_once_per_cancellation` — the *post-settlement* re-create expected `ERR_REFUND_ALREADY_ISSUED`. Settlement moves the request `VALIDATED → REFUNDED`, so PRD §2.9 priority 8 (*"The request must be `VALIDATED`, otherwise `ERR_INVALID_RESCISSION_REQUEST_STATE`"*) fires before priority 11. Changed to `ERR_INVALID_RESCISSION_REQUEST_STATE`. The *pre*-settlement `ERR_REFUND_ALREADY_ISSUED` assertion earlier in the same test is untouched and still passes, so uniqueness coverage is retained.

**Fixes applied to `test_helpers/`:**

- `test_helpers/api_client.py` — `ApiClient._request` now retries up to 3× (0.4s/0.8s backoff) on `requests.ConnectionError` only. Iteration 1 lost `test_05::test_the_same_funding_payload_reports_the_amount_once_the_window_has_expired` in all 8 rounds to `ConnectionResetError(104)` on the test's *first* request; a single-round control run passed it, proving it was a lockstep-load artifact of the per-test SIGKILL reboot (connection accepted into the dying listener's backlog, then reset by kernel teardown). A genuinely dead server stays unreachable, so real crashes still surface.

**Fixes applied to `implementation/`:**

- `workspace/implementation/app.py` — `_serve` / `_wait_for_free_port` around `app.run`: drain the port and retry the bind for up to 30s instead of dying. Werkzeug converts `EADDRINUSE` into an immediate `sys.exit(1)`, which under 8× load left the port unserved after a SIGKILL reboot race (verified: a second instance now takes over within 1s of the first being killed). No route, response field, side effect, or capability was touched — no business logic changed at all. The implementation's §2.9 precedence ordering was confirmed correct against PRD and deliberately left alone.

**Orchestrator confirmation sweep** (the Step 7 subagent removed its results files on exit): re-ran the full 8-round parallel sweep and re-materialized `workspace/implementation/results.{1..8}.json` — all 8 rounds 116/116.

## Step 8: Finalize PRD — 2026-09-01

`PRD_FINALIZED.md` is written. One edit was warranted; the other three Step 7 items were fixture-side only.

## Line counts
- `PRD.md`: 503 lines / 89,034 chars
- `PRD_FINALIZED.md`: 503 lines / 89,266 chars
- **%-delta: 0.00% lines, +0.26% characters** (one line revised in place; no lines added or removed, no new sections)

## Change list
- **§3.6 (Presentation Compliance, completion paragraph, PRD_FINALIZED.md:298)** — *revise* — reordered the completion precondition enumeration so the `review_status ≠ UNREVIEWED` gate (`ERR_INVALID_PRESENTATION_STATE`) is stated before the `disclosure_status == COMPLETE` gate (`ERR_DISCLOSURES_INCOMPLETE`), and added an endpoint-scoped sentence pinning that a presentation failing *both* reports `ERR_INVALID_PRESENTATION_STATE` — `implementation/routes/presentations.py:214-222`

## Per-edit pre-edit search log

**Edit 1 — §3.6 completion precondition order**

(a) **Subject identified:** the evaluation order of precondition gates on `POST /sales-presentations/{id}/complete`, and more broadly the relative ordering of the `ERR_DISCLOSURES_INCOMPLETE` gate against presentation-state gates anywhere in the system.

(b) **Impl paths enumerated** (grep for `DISCLOSURES_INCOMPLETE|INVALID_PRESENTATION_STATE|disclosure_status|review_status` across all of `implementation/`, then read each hit):
- `routes/presentations.py:203-234` `complete_presentation` — the Step 7 site. Order is: role → 404 → `ERR_REPRESENTATIVE_MISMATCH` → `ERR_INVALID_BOOKING_STATE` → `ERR_INVALID_PRESENTATION_STATE` (unreviewed) → `ERR_DISCLOSURES_INCOMPLETE`. Confirms §2.9's 8-before-16 precedence and contradicts the *reading order* of PRD.md's original sentence.
- `routes/agreements.py:45-53` `create_agreement` — the **other** `ERR_DISCLOSURES_INCOMPLETE` guard. Here the order is genuinely the opposite direction: `ERR_DISCLOSURES_INCOMPLETE` fires *before* `ERR_PRESENTATION_NOT_CLEARED` (§2.9 priority 16 before 17). This is the path that forced the wording adjustment in (c).
- `routes/presentations.py:82-86` acknowledgment append — `ERR_INVALID_PRESENTATION_STATE` when `disclosure_status` is no longer `PENDING`/`PARTIAL`. Unrelated to the completion gate but shares the error code.
- `routes/presentations.py:161-173` `review_presentation` — `ERR_INVALID_PRESENTATION_STATE` for illegal `CLEAR`/`FLAG` transitions; again shares the code.
- `derive.py:118-129` `recompute_disclosures`, `derive.py:141-148` `recompute_compliance_score`, `derive.py:197-220` `enter_flagged`/`maybe_auto_flag` — every writer of `disclosure_status` and `review_status`; none is affected by a precondition-ordering sentence.
- `errors.py:39,54` — code/status registry only.

(c) **Wording adjustment made:** the first draft said the state gate is checked before disclosure completeness without qualification. That would have mis-described `routes/agreements.py:50-53`, where disclosures are checked *first* and the clearance gate second. I therefore scoped the new sentence to "**On this endpoint** those two gates are evaluated in exactly that order", named only the two codes actually involved, and left §3.7's agreement-execution ordering (disclosures → `ERR_PRESENTATION_NOT_CLEARED`) verbatim and untouched.

## Items that needed no PRD change
- **`test_14_endpoints.py` `PENDING` → `PARTIAL`** — `derive.recompute_disclosures` (`derive.py:118-128`) yields `COMPLETE`/`PARTIAL`/`PENDING` exactly as PRD §3.6 already states; `calc.compliance_score` (`calc.py:220-222`) matches the §3.6 expression verbatim. Pure fixture bug.
- **`test_11` refund re-create → `ERR_INVALID_RESCISSION_REQUEST_STATE`** — `routes/rescission.py:140-149` checks `status != "VALIDATED"` before the uniqueness scan before segregation (8 → 11 → 15), which is already the order both §2.9 and the §3.9 sentence give. Pure fixture bug.
- **`test_helpers/api_client.py` `ConnectionError` retry and `app.py` `_serve`/`_wait_for_free_port`** — transport/process-lifecycle only. `app.py:63-105` touches no route, response field, side effect, or capability, so there is no API behavior for the PRD to describe.

## Step 9: Complete PRD — 2026-09-01

PRD_COMPLETED.md is written.

## Files
- Source: `workspace/PRD_FINALIZED.md` — 503 lines, 89,266 chars
- Output: `workspace/PRD_COMPLETED.md` — 503 lines, 93,227 chars (**+3,961 chars**, 20 lines touched, no lines added/removed, no new sections)

## Counts
- ambiguity-pins: **14**
- mismatch-revisions: **6**

(Cross-reference: `results.8.json` shows 116/116 tests passing against this implementation, so tests never contradicted impl as the alignment target.)

## Changes
- §2.1 Identity/RBAC — revise — ambiguity — a blank (whitespace-only) `X-User-ID`/`X-User-Role` is treated as absent → `ERR_UNAUTHENTICATED` — `auth.py:32`
- §2.3 Pagination and List Ordering — insert — ambiguity — every `created_at`/`executed_at` tie in lists, cascades and the rotation chain is broken last by in-process creation order — `store.py:62`, `routes/bookings.py:222`, `routes/ops.py:37`
- §2.9 item 3 — insert — ambiguity — bounds for the previously unbounded fields: booking `reason` 1–300; `funding_reference`/`recording_reference`/`recording_jurisdiction`/`settlement_reference` 1–120; `collected_amount_cents` and `modules_completed` ≥ 0; every `expected_*_version` ≥ 1 — `routes/bookings.py:130`, `routes/agreements.py:157`, `routes/closing.py:24`, `routes/rescission.py:196`, `routes/retraining.py:77`
- §2.10 Cascades — insert — ambiguity — a recomputation landing on the already-stored value is not a mutation: `updated_at`/`version` stay put (idempotent close/reinstate advance nothing) — `derive.py:9`, `envelope.py:67`
- §3.1 channel reinstate — revise — mismatch — no state gate; reinstate is also accepted on an already-`ACTIVE` channel — `routes/channels.py:61`
- §3.2 gallery create — revise — mismatch — `site_code` uniqueness is not enforced; the only check is "no lower-case letter" → `ERR_INVALID_REQUEST` — `routes/galleries.py:25`
- §3.2 gallery set-status — revise — mismatch — an `OPEN` request re-derives from *any* current posture (not just `CLOSED`), and `CLOSED` on an already-closed gallery is accepted — `routes/galleries.py:60`
- §3.2 representative create — revise — mismatch — `license_number` global uniqueness is not enforced — `routes/galleries.py:86`
- §3.4 booking cancel — revise — ambiguity — the rep is released only from `ON_TOUR`; a `SUSPENDED`/`RETRAINING` rep is left as-is — `routes/bookings.py:271`
- §3.6 acknowledgments — revise — ambiguity — an append once `disclosure_status` is `COMPLETE` is rejected with `ERR_INVALID_PRESENTATION_STATE` — `routes/presentations.py:82`
- §3.6 review — revise — ambiguity — `FLAG` is reachable from `UNREVIEWED` only; from `CLEARED`/`FLAGGED` → `ERR_INVALID_PRESENTATION_STATE` — `routes/presentations.py:169`
- §3.6 complete — revise — ambiguity — `tours_taken_count` rises even if the rep is no longer `ON_TOUR`; the presentation record is unmodified so its `version` does not advance; the response returns the presentation — `routes/presentations.py:224`
- §3.6 projections — insert — ambiguity — validation order on the two sub-resource lists: `limit`/`offset`, then presentation `{id}`, then the enum filter — `routes/presentations.py:254`
- §3.8 funding — revise — mismatch — the `AWAITING_FUNDING` gate (`ERR_INVALID_AGREEMENT_STATE`) is evaluated *before* the `EXPIRED` gate (`ERR_RESCISSION_PERIOD_ACTIVE`), reversing the prose order — `routes/agreements.py:161`
- §3.8 underwriting decision — revise — mismatch — the sub-620 `APPROVE` refusal (`ERR_INVALID_REQUEST`) precedes the `SUBMITTED` state gate; `DECLINE` is unaffected by a `RESCINDED` agreement — `routes/financing.py:92`
- §3.8 closing — revise — ambiguity — recording gates package state (`ERR_INVALID_CLOSING_PACKAGE_STATE`) then agreement `FUNDED` (`ERR_INVALID_AGREEMENT_STATE`); delivery gates on nothing else; both return the package — `routes/closing.py:28`
- §3.9 rescission intake — revise — ambiguity — every `fulfillment_status` other than `AWAITING_FUNDING` (incl. `VOIDED`, `TRADED_IN`) refuses with `ERR_AGREEMENT_ALREADY_FUNDED` — `routes/rescission.py:32`
- §3.9 timely branch — insert — ambiguity — the rep moves to `RETRAINING` only from `ACTIVE` — `routes/rescission.py:101`
- §3.9 settle — insert — ambiguity — requires `PENDING`, else `ERR_INVALID_RESCISSION_REQUEST_STATE` (reused for the disbursement dimension) — `routes/rescission.py:198`
- §3.9 retraining uniqueness — insert — ambiguity — `ERR_RETRAINING_ALREADY_ACTIVE` guards the manual create only; both cascades append unconditionally and can leave two active assignments sharing a reason — `derive.py:209`, `routes/rescission.py:94`

## Pipeline complete — 2026-09-01

All 9 steps done. Final artifacts present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (10 files), `test_suite/` (conftest + 18 modules, 116 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (+ `results.{1..8}.json`, all 116/116).
