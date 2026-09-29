# Worklog — task_2503_thesis_and_dissertation_format_review_deposit

## Step 1: Create task directory — 2026-09-03T02:40:26.859Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit` and its `workspace/` subdirectory. Index 2503 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T04:25:22.573Z

All three artifacts are complete and lint-clean.

**Files** (full paths):
- `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/SCAFFOLD_CORNER_DESIGN.yaml`

**§1.0–§1.7 (SCAFFOLD.yaml)** — `api_prefix: /graduate-school`, archetype `workflow_orchestration` + `compliance_audit`, `difficulty_level: expert_plus`, entity topology `graph`, state-machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`; layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation.
- 14 entities, 12 state machines (Thesis carries two independent dimensions), 2 concurrency rules, 15 calculations, 40 validations (one pinned priority ladder), 47 endpoints (20 GET, 27 POST/DELETE incl. `_clock/set_current_utc`), 50 errors, 6 roles (Student/FacultyMember entity_backed; the other four opaque).

**§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml)** — 9 rule_ids × 2 = **18 instances**, all with full `test_recipe` chains.

**§1.9 (SCAFFOLD_CORNER_DESIGN.yaml)** — **9 sections, 82 instances** (65 with `test_recipe`, 17 `excluded_because` stubs pointing at named §1.8 instances): entities 12, state_machines 13 (3 stubs), calculations 12 (4), validations 16 (5), endpoints 5 (1), errors 9 (1), rbac 6, cross_cutting_complexity_layers 8 (3), consistency_model 1.

**Verification** — every one of the 50 error ids is referenced by a §1.8/§1.9 instance; no duplicate `name` across the two design files; every cited `difficulty_instance` exists; no stub carries a `test_recipe`; no forbidden concurrency vocabulary remains (two innocuous uses of "simultaneously" were rewritten); `SCAFFOLD.yaml` contains neither design key and each design file has exactly one top-level key.

Final lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1393

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Note: the task directory also contains a pre-existing `worklog.md` and empty `workspace/` that I did not create or touch. The hard constraint held throughout — no sibling task directory was listed, globbed, grepped or read.

## Step 3: Copy shared files — 2026-09-03T04:25:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T04:41:00.000Z

PRD generated and verified.

**Artifact:** `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/workspace/PRD.md` (417 lines, ~12.5k words)

**Structure:** §1 Introduction → §2 Global Specifications (12 subsections, §2.2 emitted byte-verbatim from `section-2.2-response-structure.md`) → §3 Business Logic & Workflows (9 subsections) → §4 Endpoint Definitions (4-column table) → §5 Error Code Catalogue (2-column table). File ends at the last §5 table row — no audit footer, no Hard Contract report inside the document.

**Hard Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 100 required / 100 present / 0 missing
- `endpoints[].request_body` + `input`: 59 / 59 / 0 missing
- `endpoints[].query_params`: 10 / 10 / 0 missing
- `path_params`: 1 / 1 / 0 missing
- Also present: all 51 state-machine state values, all enum field values, and all computed output-object fields (`projected_late_fee_cents`, `next_blocking_error_id`, `withheld_count`, `pending_count`, `conferred_count`, `outstanding_items`, `projection_variant`, `current_utc`, `to_iso8601`)

**Hard Contract 2 — Rule Coverage: PASS**
All 15 calculations (with every named constant and pinned evaluation order), all 12 state machines' transitions/preconditions/side effects — including both dimensions on `Thesis` (`workflow_state`, `integrity_state`), both `concurrency_rules` (write endpoint + `expected_thesis_version` + `ERR_STALE_THESIS_VERSION` + 412), all 40 validation priorities (expressed once as a 16-stage admission ladder in §2.5, with each rule's condition and `applies_to` scope stated in the owning §3 subsection), all field defaults/initials, and every sibling-branch group at equal prose density (3 defense outcomes, 4 embargo decisions, 3 permission reviews, 3 screening actions, 2 format decisions, both clearance variants, both embargo release anchors).

**Hard Contract 3 — §3 Path Purity: PASS**
948 backtick tokens scanned in §3: 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. Endpoint paths appear only in §2 and §4.

**Anti-truncation verification (requested counts):** 47/47 endpoint paths present, 47 rows in the §4 table; 50/50 error IDs present, 50 rows in the §5 table; tail ends at a complete section boundary.

**One repair pass beyond the contracts:** a fuzzy-language scan caught 4 genuine hedges, all replaced with deterministic wording — "as appropriate" on FK-error selection → "according to which referenced record could not be found"; "the clearance typically falls from `PENDING_ITEMS` back to `BLOCKED`" → statement that the committee-approval item is no longer satisfied (avoids asserting a status the projection rules derive); "carrying into the year as needed" → "carrying into the following year each time the running month index passes December"; "deposit is usually the last outstanding item" → conditional on no other outstanding item remaining. Re-ran all three contracts after the edits; the scan is now clean (remaining `around` matches are substrings of `turnaround`).

The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator anti-truncation re-verification (independent of the subagent):** `PRD.md` is 416 lines / 91634 bytes with 5 top-level sections; §5 (last section) contains exactly 50 `ERR_` table rows and the file's final line is a complete table row, so it ends at a real section boundary. Diffing error ids against `SCAFFOLD.yaml` yields one scaffold-only token, `ERR_XXX`, which is a template placeholder in the scaffold's own prose rather than a declared error — all 50 real error ids are present. §4 has 47 endpoint rows. Not truncated; no regeneration needed.

**Orchestrator note on Steps 5 and 6:** both were launched concurrently in a single assistant message, per the skill's physical-isolation requirement — the implementation generator started before `test_suite/` existed on disk and was additionally instructed not to read `test_helpers/`, while the test generator was instructed not to read `workspace/implementation/`. Both confirmed compliance.

## Step 5: Generate unit tests — 2026-09-03T05:50:05.581Z

Test generation is complete and verified.

## Files written

`test_helpers/` (Stage 1, 9 modules): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/` (Stage 2, 18 modules, 101 tests):

| file | tests | source |
|---|---|---|
| test_01_dual_variant_calc … test_09_compensating_invariant (9 files) | 36 | queue A, 4 per rule_id |
| test_10_entities.py | 12 | queue B `entities` |
| test_11_state_machines.py | 10 | queue B `state_machines` |
| test_12_calculations.py | 8 | queue B `calculations` |
| test_13_validations.py | 11 | queue B `validations` |
| test_14_endpoints.py | 4 | queue B `endpoints` |
| test_15_errors.py | 8 | queue B `errors` |
| test_16_rbac.py | 6 | queue B `rbac` |
| test_17_cross_cutting_complexity_layers.py | 5 | queue B `cross_cutting_complexity_layers` |
| test_18_consistency_model.py | 1 | queue B `consistency_model` |

## Counts per queue

- Queue A (Difficulty §1.8): 18 instances, all 18 covered, 36 tests (2 per instance).
- Queue B (Corner §1.9): 82 instances, 65 non-stub, all 65 covered, 65 tests (strictly 1:1).
- Total 101 tests, 83 distinct `Design:` tags, 0 unresolved tags, 0 untagged tests, 0 dual-tagged tests.

## Instances skipped

**None for PRD silence.** Every non-stub instance in both indices passed the two-condition filter and produced a test. The 17 uncovered corner instances are stubs — the corner index itself gives each one an `excluded_because.difficulty_instance` pointer instead of a recipe (deliberate dedup against queue A). I verified programmatically that all 17 pointers resolve to difficulty instances that exist and are covered by an emitted queue-A test, so nothing falls through the gap: state_machines ×3, calculations ×4, validations ×5, endpoints ×1, errors ×1, cross_cutting ×3.

## Verification

- `py_compile` clean on all 18 test modules and 9 helper modules.
- `pytest --collect-only`: 101 tests collected, 0 errors.
- Citation pass: 112 `PRD §X.Y: "…"` quotes, every one a literal substring of `workspace/PRD.md`.
- Tag pass: all tags resolve to a real `name:` in the source YAML; no duplicate queue-B tags.
- pyflakes: no findings in `test_suite/` (only the intentional re-export facade in `test_helpers/__init__.py`).
- No `skip`/`skipif`/`xfail`/placeholder anywhere; no docstring or comment mentions "scaffold".
- Nothing under `workspace/implementation/` was read or written.

## Deviations worth relaying

1. Queue A instance 8 (`transitive_cascade/integrity_uphold_…`): its recipe asserts `FormatReview.fr1.status == VOID` for a cycle that is `ACCEPTED`, which contradicts PRD §3.6 ("every one of its format review cycles whose `status` is `PENDING_REVIEW` or `REVISIONS_REQUIRED` is moved to `VOID`"). That one assertion is omitted; the rest of the cascade is asserted.
2. `errors/announcement_lead_of_nine_business_days_rejected` specifies term code `2026FA_LATE`, which PRD §2.5 forbids (`YYYY` + `SP|SU|FA`). Kept `2026FA` and overrode only the deadlines; the 9-vs-10 business-day boundary is still what the test pins.
3. `cross_cutting/documented_permission_count_reconciles_after_each_review_decision` creates a `WRITTEN_PERMISSION` record with no `document_uri`, which PRD §3.5 refuses with `ERR_PERMISSION_EVIDENCE_MISSING`. Added a `document_uri` so the setup is legal; the count-reconciliation ladder (0 → 1 → 1 → 2 → 3) is unchanged.
4. One pre-existing queue-B duplication was repaired this session: `state_machines/embargo_information_loop_returns_to_requested_and_counts_the_request` had been split across two tests (a dual-tag). They are now merged into a single test that walks `REQUEST_INFO` → supplement → `APPROVE` and asserts the instance's full assert list, which is why test_11 holds 10 tests rather than 11.

## Step 6: Generate implementation — 2026-09-03T05:50:05.581Z

All three smoke passes are green (`smoke OK`, `smoke B OK`, `smoke C OK`). The implementation is complete.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/workspace/implementation/`:

- Launcher/deps: `start.sh` (guarded `pip install`, then `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000), `requirements.txt`
- Core: `app.py` (`create_app()`, `ApiError`/`HTTPException`/catch-all handlers, `threaded=False`), `errors.py`, `response.py` (envelope + pagination meta), `db.py` (14 in-memory dicts, empty at boot), `validate.py`, `middleware.py` (`X-User-ID`/`X-User-Role`), `lookup.py`, `serializers.py`, `logical_clock.py`, `timeutil.py` (business days, 5 holidays, month arithmetic with day clamping)
- Services: `services/calc.py` (severity score, turnaround, late fee, embargo caps, metadata score, adjusted similarity), `services/counters.py`, `services/clearance.py` (dual PROVISIONAL/FINAL projection), `services/__init__.py`
- Routes: `routes/{__init__,common,reference,theses,committees,defense,reviews,permissions,embargo,integrity,deposits}.py`

**47 endpoints** implemented (27 mutating + 20 reads), 50 error codes, 14 entities. Storage is process-local dicts only; nothing is seeded, and no file/SQLite/JSON persistence exists.

## Ambiguities and the interpretations chosen

1. **Stage-11 `ERR_THESIS_STATE_INVALID` scope.** The PRD narrative reads as if every defense operation checks thesis state, but scaffold priority 11's `applies_to` lists only the seven creating endpoints. So `announce`/`outcome`/`cancel` check only `ERR_DEFENSE_STATE_INVALID` — re-announcing an ANNOUNCED event returns that, not a thesis-state error.
2. **ACCEPT guard order.** §3.5's prose orders permissions before the defect score; §2.5 stage 16 orders DEFECT_SCORE before PERMISSIONS_INCOMPLETE. I followed the stage-16 ladder (it is the normative precedence list).
3. **`POST /integrity-screenings/{id}/action` term gating.** Not gated on `ERR_TERM_DEPOSIT_CLOSED` — it is absent from §2.9's 18-operation list and from priority 9's `applies_to`. The screening *create* is gated. An officer can therefore still uphold a finding after the term closes.
4. **UPHOLD precedence.** Checks thesis-terminal state before screening status.
5. **Uniqueness violations have no declared error code** (term `code`, student/faculty `email`, room `code`, one Committee per Thesis) → `ERR_INVALID_REQUEST` 400. The one-committee-per-thesis check runs *after* the stage-9 term check because priority 12 excludes `POST /committees`.
6. **Deposit handle sequence.** Computed over `DEPOSITED` rows of the same term ordered by `(created_at, version, _seq)` and assigned by direct field set, so the new deposit row stays at `version` 1.
7. **Screening lifecycle.** Rows are created directly in their resolved `CLEARED`/`FLAGGED` status at version 1; no client ever observes an intermediate `SCREENED`.
8. **`review_note`** on a format decision is accepted in the body but not persisted — `FormatReview` has no such field.
9. **Clock and timestamps.** `api_request_timestamp` uses the logical clock; every datetime is normalized through one `iso()` helper (3 fractional digits + `Z`), so a clamped `revision_due_at` is byte-identical to the term deadline.
10. **Thesis creation** writes the clearance row as `BLOCKED`/`PROVISIONAL` with empty `outstanding_items` and does not run a recompute.
11. **Version bumps.** `write()` always bumps; `reconcile()` bumps only on an actual value change (derived counters, cascaded rows, clearance, student mirrors). Both guarded creates (`permission-records`, `embargo-requests`) bump `Thesis.version` by exactly one.
12. **Array endpoints declared `input: []`** still honour `limit`/`offset` and emit pagination meta.

Verified live: severity score against the scaffold example (101 pages, 1/2/4 → 8.17) and independently (220 pages, 2/3/4 → 28.93); late fee with the 11-bday turnaround grace tier (deadline 2026-11-02 → effective 11-05, deposit 11-10 → 7500); MASTERS `PUBLISHER_AGREEMENT` cap 6; `PARTIALLY_APPROVED` release anchored to conferral (2026-12-18 + 3mo → 2027-03-18); handle `2027SP/00001`; committee revert and integrity-uphold cascades; FAIL dissolving the committee and releasing chair load; `ERR_DUPLICATE_THESIS_FOR_TERM` not firing after a failed attempt.

## Step 7: Run tests and iterate — 2026-09-03T06:11:48.882Z

Clean 8-round parallel sweep achieved.

## Summary

**Iterations run:** 2 (each an 8-round parallel `--isolation per-test-server` sweep, 101 tests/round).

- **Iteration 1:** all 8 rounds 98/101. Union of failures = 3 tests (same 3 in every round).
- **Iteration 2:** all 8 rounds **101/101**.

**Tests deleted:** none.

**Fixes applied to `test_suite/`** (both are STEP 1c partial-coverage / STEP 2 faithfulness corrections; no assertion was weakened to an HTTP-status check and no skip/xfail was added):

1. `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/test_suite/test_15_errors.py` — `test_the_deposit_ladder_runs_metadata_then_fee_then_duplicate`: the second deposit of the same row expected `ERR_DEPOSIT_ALREADY_EXISTS`, but PRD §2.5 puts stage 11 (`ERR_THESIS_STATE_INVALID`) ahead of stage 16 (`ERR_DEPOSIT_ALREADY_EXISTS`), and §3.8's first gate is "The document must be `FORMAT_ACCEPTED`, or the attempt is `ERR_THESIS_STATE_INVALID`" — a successful deposit has already advanced the document `FORMAT_ACCEPTED → DEPOSITED`. The ladder uniquely determines `ERR_THESIS_STATE_INVALID`/409; the assertion now expects that exact error_id. (Implementation was correct.)

2. `/home/ubuntu/github/CodingPRD/tasks/task_2503_thesis_and_dissertation_format_review_deposit/test_suite/test_16_rbac.py` — `test_the_outcome_endpoint_denies_the_wrong_role_and_the_wrong_faculty`: removed `assert held["outcome"] == "PASS"` (COMPUTED-FIELD SILENCE). PRD §3.4 enumerates the DefenseEvent's own fields as `announced_at`, `announcement_lead_bdays`, `outcome_note`, `cancellation_reason`; `outcome` appears only as the request-body input, and the recorded result is carried by `status`. The only PRD text suggesting a visible `outcome` is the §4 routing-table description cell ("…with its announcement lead and outcome"), which admits both readings. The covered assertion (`status == "HELD_PASS"`, verbatim in §3.4) was kept, as were the thesis- and committee-state assertions.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened.

**Key finding on the third iteration-1 failure — `test_the_analyst_who_accepted_the_format_may_not_deposit_it`:** it failed in all 8 round-1 files with `ConnectionResetError(104)` raised inside `test_helpers/fixtures.py:171` (the third trivial `POST /faculty-members` of `setup_reference_data`) — an endpoint with no timing logic. It passed cleanly when run in isolation through the runner, and passed in all 8 rounds of iteration 2 with no code change touching that path. Diagnosis: a stale keep-alive connection in the session-scoped `requests.Session` after the runner's per-test server restart, aggravated by the 8× CPU contention on this host — infrastructure, not an artifact defect. I deliberately did **not** "fix" the implementation for it.

**Orchestrator independent verification of the final sweep:** all 8 `workspace/implementation/results.{1..8}.json` exist, parse as JSON, and each reports `passed=101 total=101 failed=0 errors=0 skipped=0`. Their mtimes cluster at 06:03:50–06:03:51, consistent with 8 genuinely concurrent rounds joined by `wait` rather than a serial or partial run. `grep -c Terminated workspace/sweep.log` = 0, so the setsid wrapper held and no round was reaped by SIGTERM. The claimed green sweep is real.

## Step 8: Finalize PRD — 2026-09-03T06:19:57.753Z

Step 8 was NOT skipped: Step 7 ran 2 iterations and applied 2 `test_suite/` fixes, so the zero-iteration skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) did not hold.

PRD_FINALIZED.md written.

## Line counts
- `PRD.md`: 416 lines; `PRD_FINALIZED.md`: 416 lines; **0.00% line delta** (2 lines revised in place, no lines added or removed, no new sections).

## Changes
- **§3.4 (defense outcome recording)** — revise — added that `outcome` is a request-body input only, is not persisted as a `DefenseEvent` field, that the selected branch is carried by the event's `status`, and that the event's own recorded fields remain `announced_at`, `announcement_lead_bdays`, `outcome_note`, `cancellation_reason` — `implementation/serializers.py:137-152`, `implementation/routes/defense.py:275-279`.
- **§4 routing table, `GET /defense-events/{id}`** — revise — description cell "with its announcement lead and outcome" → "with its announcement lead and the outcome carried by its `status`", removing the only PRD text implying a visible `outcome` field — `implementation/serializers.py:137-152`.

## Per-edit pre-edit search log

**Edit 1 + 2 (single subject, applied as two sentences)**
- (a) **Subject:** whether a `DefenseEvent` persists/exposes an `outcome` field, and what the event's field set is.
- (b) **Paths enumerated:** `serializers.py:137-152` (`defense_event`, the *only* defense-event serializer — no `outcome` key); its six callsites `routes/defense.py:62` (single read), `:85` (list), `:196` (schedule 201), `:232` (announce), `:290` (record outcome), `:317` (cancel) — all return the same field set; the single row-creation path `routes/defense.py:179-190` (`new_row(... status, announced_at, announcement_lead_bdays, outcome_note, cancellation_reason)`, no `outcome`); every `write()` on an event: `:223-228` (announce), `:275-279` (outcome → `status`+`outcome_note` only), `:311` (cancel); the two off-Step-7 cascade writers `routes/common.py:127` and `routes/committees.py:54` (committee-composition-change cascade → `status="CANCELLED"`, `cancellation_reason` only); repo-wide `grep -rn "outcome"` confirming the only persisted names are `outcome_note` (field) and `outcome` (request-body enum in `validate.req_enum`), plus `grep -rn "defense_events\["` confirming exactly one insertion site.
- (c) **Wording adjustment:** scoped the negative claim to the `DefenseEvent` entity ("not persisted as a field of the `DefenseEvent`") rather than a blanket "the API never returns an outcome", since `outcome` remains a required request-body enum (`routes/defense.py:240`) and `outcome_note` *is* a persisted field. Positive re-listing of the field set was taken verbatim from the existing §3.4 booking sentence so it stays consistent with the creation path and all six response paths.

## Items deliberately not edited
- **Step 7 test_suite fix 1** (`test_15_errors.py`, second deposit → `ERR_THESIS_STATE_INVALID`): verified `routes/deposits.py:52-56` gates on `workflow_state != "FORMAT_ACCEPTED"` before the `ERR_DEPOSIT_ALREADY_EXISTS` check at `:83-86`, matching §3.8's first gate and §2.5 stage 11 < stage 16 verbatim. PRD already uniquely determines this; prose kept byte-identical.
- **Third iteration-1 failure** (`ConnectionResetError` in `fixtures.py:171`): host infrastructure, no PRD implication, no edit.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields 8 lines — exactly the two claimed in-place line revisions (§3.4 prose at line 217, §4 routing-table cell at line 329), no additions or deletions. Both trace to Step 7 diff item 2. Scope held.

## Step 9: Complete PRD — 2026-09-03T06:46:49.219Z

**Orchestrator decision (recorded per the autonomy instruction):** Step 9 was run as THREE sequential file-partitioned passes over `workspace/implementation/` rather than one monolithic subagent. Rationale: the implementation is 3794 lines across 25 modules, and a single agent asked to "walk implementation/ exhaustively" at that size reliably under-scans — the known failure signature is a `PRD_COMPLETED.md` that comes back byte-identical (or near-identical) to its source, meaning the scan never really ran. Each pass owned a disjoint file partition, edited the same `PRD_COMPLETED.md` in place (pass A created it from `PRD_FINALIZED.md`; passes B and C were explicitly told not to re-copy or overwrite), and handed forward notes on behaviors that belonged to a later partition. Partitions: (A) app, db, errors, response, middleware, validate, lookup, serializers, timeutil, logical_clock, routes/{__init__,common,reference,theses}; (B) routes/{committees,defense,reviews}, services/calc; (C) routes/{permissions,embargo,integrity,deposits}, services/{counters,clearance}, plus the live `integrity_upheld_cascade` in routes/common.py that pass A had not audited.

### Pass A — core + reference + theses (18 edits: 13 ambiguity-pins, 5 mismatch-revisions)

416 → 416 lines; 91,946 → 97,361 bytes (+5,415).

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars, regenerated per response including errors — response.py:14-15
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and negative `offset` are `ERR_INVALID_REQUEST`, and page params are validated before path 404s — validate.py:137-157, theses.py:99-101
- §2.3 — insert — ambiguity — `created_at` ordering ties broken by insertion order (holds for every list, incl. defense-events' last key) — db.py:77-84
- §2.4 — insert — ambiguity — instants rendered with 3 fractional digits by truncation, unset instants as JSON null — timeutil.py:18-31, serializers.py
- §2.4 — insert — ambiguity — inbound instant parsing: `Z` or numeric offset accepted, zone-less read as UTC, time-less read as midnight, else `ERR_INVALID_REQUEST`; clock may move backward — timeutil.py:42-57, logical_clock.py:19
- §2.5 stage 3 — insert — ambiguity — body must be a JSON object; explicit `null` counts as absent; absent body = empty object; bool rejected for int/number; required strings accept `""` except defense `cancellation_reason` — validate.py:17-40, 56, 75
- §2.7 — revise — mismatch — "instants derived by arithmetic carried to whole seconds" → they preserve the source time-of-day including fractional seconds (no truncation anywhere) — timeutil.py:88-97, 107-116
- §2.7 — insert — ambiguity — decimals are JSON numbers, so `0.8500`→`0.85`, `12.00`→`12.0` — serializers.py:8-13
- §3.1 — insert — ambiguity — duplicate/malformed term `code` both `ERR_INVALID_REQUEST` (pattern first); no ordering enforced among the three term instants; no cap on announcement lead — reference.py:84-91, 81-83
- §3.1 — insert — ambiguity — duplicate student email / faculty email / room code each `ERR_INVALID_REQUEST`; `seat_capacity` never checked against an audience — reference.py:114-116, 139-141, 165-167
- §3.2 — revise — mismatch — `document_type` vs `degree_level` is a convention the API never cross-checks; `document_type` drives composition, `degree_level` drives embargo caps — theses.py:212, committees.py:249
- §3.2 — insert — ambiguity — opening a thesis does not run the clearance projection; an existing clearance row is untouched — theses.py:251, clearance.py:118-133
- §3.2 — insert — ambiguity — bad `workflow_state` filter is `ERR_INVALID_REQUEST`; unresolvable `student_id`/`term_id` filters just match nothing — theses.py:59-69
- §3.7 — revise — mismatch — month-anchor time-of-day preserved exactly, fractional seconds included — timeutil.py:100-116
- §3.8 — revise — mismatch — `next_blocking_error_id` pinned to the exact 7-step chain, explicitly excluding duty-segregation/metadata/late-fee; projected fee computed even when deposit impossible — theses.py:160-198
- §3.9 — revise — mismatch — projection runs on §3.3–§3.8 mutations, with thesis creation as the stated exception — theses.py:251
- §3.9 — insert — ambiguity — conferral's withheld branch also nulls `cleared_at` and mirrors notation/`degree_conferred=false` — reference.py:233-246
- §3.9 — revise — mismatch — conferral tallies (and `conferred_count`) count processed documents, not distinct candidates — reference.py:219-283
- §4 intro / §5 preamble — insert — ambiguity — trailing slashes accepted; unmatched path → `ERR_INVALID_REQUEST` 404, disallowed method → `ERR_INVALID_REQUEST` 405, both before header checks (noted as the exception to §5's 400) — app.py:20, 28-39

**Pass A scanned and already fully pinned (no edit):** `errors.py` (every id's HTTP status matches §5 exactly), `lookup.py` (per-entity 404 ids and reverse-reachability collections match §2.5/§2.12), `middleware.py` (ladder stages 1–2 order and the six roles), `serializers.py` field lists (every field of all 14 entities is named in PRD prose), `routes/__init__.py`, `routes/common.py` (owner/version/term/permission/embargo helpers match §2.6–§2.9, §3.5, §3.6). Hand-off raised: `common.revert_approved_committee` is dead code — the live seat-change cascade is inlined in `routes/committees.py:30-60`.

### Pass B — committees, defense, reviews, calc (9 edits: 7 ambiguity-pins, 2 mismatch-revisions)

97,361 → 100,297 chars (+2,936); 416 lines unchanged.

- §3.3 ¶1 — insert — ambiguity — a duplicate committee create is `ERR_INVALID_REQUEST` (400), and no thesis `workflow_state` guards the create (only ownership + term window) — routes/committees.py:112-116
- §3.3 ¶2 (seat list) — insert — ambiguity — unknown `committee_id`/`faculty_id` match nothing rather than 404; out-of-enum `status` is `ERR_INVALID_REQUEST` — routes/committees.py:79-89
- §3.3 (dean's ruling) — insert — ambiguity — `rejection_note` belongs to the `REJECT` branch alone: ignored on `APPROVE` (which leaves an earlier note standing), and always overwritten by `REJECT` so a noteless second rejection resets it to null — routes/committees.py:274, 306-313
- §3.3 (pending-decision seat changes) — revise — mismatch — "chair load stays at zero" was a false universal (the recompute is global over all faculty); now says the *seat* contributes nothing and other committees' load is unaffected — services/counters.py:19-22, services/calc.py:149-165
- §3.3 (cascade) — insert — ambiguity — **[pass A hand-off]** the no-revert case: on an `APPROVED` committee whose document has left the three trigger states, none of the four steps fire — committee stays `APPROVED` with the grant intact, `workflow_state` unchanged, no event cancelled, no room counter moved; only counts/chair loads/clearance recompute, and the committee `version` still advances — routes/committees.py:37-61
- §3.4 ¶2 — revise — mismatch — "at most 240 **whole** minutes" implied truncation; impl compares the exact difference (`timeutil.whole_minutes` returns a float), so 30m30s passes and 240m01s fails; end ≤ start fails the floor — routes/defense.py:122-130, timeutil.py:119
- §3.4 (successful booking) — insert — ambiguity — `booked_minutes_total` truncates each event's duration downward to whole minutes before summing (a 30m30s booking contributes 30); plus unknown `thesis_id`/`room_id` filters match nothing — services/calc.py:171-181, routes/defense.py:70-80
- §3.5 (format decision) — insert — ambiguity — `review_note` is validated then discarded; `FormatReview` has no note field and none is echoed — routes/reviews.py:40, serializers.py:155-174
- §3.5 (ACCEPT guards) — insert — ambiguity — concrete guard order made explicit (screening → integrity hold → defect score → permissions), since the narration order differs and the score/permissions pair is observable — routes/reviews.py:56-76

**Pass B scanned and already fully pinned (no edit):** `services/calc.py` — every formula was already uniquely pinned (severity-weighted score's per-subtotal rounding and density floor, revision window with long-doc bonus and deadline clamp, `analyst_turnaround_bdays_total`, announcement lead, composition minimums and chair-load derivation, `room_overlap` vs `faculty_overlap`, adjusted similarity + 18.00 flag, embargo caps/halving/governing-request/release anchors, metadata score and the six-step late fee, `conferral_notation`); only `room_booked_minutes_total`'s per-event truncation was unpinned. `routes/defense.py` — chair-identity rule already covered by pass A's §2.1 edit; check order, buffered vs half-open arithmetic, three outcome branches, FAIL→`DISSOLVED`, cancel compensation, and list ordering all matched.

### Pass C — permissions, embargo, integrity, deposits, counters, clearance (11 edits: 8 ambiguity-pins, 3 mismatch-revisions)

100,297 → 102,126 chars (+1,829); 416 lines unchanged.

- §2.5 stage 3 — insert — mismatch — path identifiers in the URL are resolved *before* the body-shape half of stage 3, so an action posted at an unknown id reports its 404 even with a malformed body (query-param half still runs first, per §2.3) — routes/permissions.py:105, routes/embargo.py:104,188, routes/integrity.py:89 (verified live: 404, not 400)
- §2.6 — insert — ambiguity — `expected_thesis_version` is a whole number of at least 1, so 0/negative is `ERR_INVALID_REQUEST` at stage 3, not `ERR_STALE_THESIS_VERSION` — routes/permissions.py:46, routes/embargo.py:50 (verified live)
- §3.5 — revise — ambiguity — a permission ruling stores `review_note` verbatim; a ruling sent without one resets it to null — routes/permissions.py:108,131 (verified live)
- §3.6 — revise — mismatch — the screening row is persisted already resolved, so it is born at `version` 1 carrying `CLEARED`/`FLAGGED` (no separate `SCREENED` write) — routes/integrity.py:61-72 (verified live)
- §3.6 — insert — ambiguity — the document row is written on every screening, so its `version` advances even when the resolved `integrity_state` repeats — routes/integrity.py:80 (verified live)
- §3.6 — insert — ambiguity — a `similarity_pct`/`excluded_quoted_pct` outside 0–100 is `ERR_INVALID_REQUEST` — routes/integrity.py:36-39
- §3.6 step 3 — insert — ambiguity — the counter re-derivation is a second write on the document row, so its `version` advances twice across the cascade when `analyst_turnaround_bdays_total` actually moves and once when it does not — routes/common.py:151 (verified live: +2)
- §3.7 — insert — ambiguity — `approved_months` is type-validated on every decision but read only by `PARTIALLY_APPROVE`; `decision_note` is stored by all four branches (an omitted note clears an earlier one), and a supplement leaves it untouched — routes/embargo.py:107,136-178,203
- §3.7 `REQUEST_INFO` — revise — ambiguity — `decided_by_user_id` is left null alongside `decided_at` — routes/embargo.py:172-178
- §3.8 — insert — ambiguity — `abstract_word_count` and `late_fee_paid_cents` are whole numbers ≥ 0, so a negative tender is `ERR_INVALID_REQUEST`, not `ERR_LATE_FEE_MISMATCH` — routes/deposits.py:40,42
- §3.8 — revise — mismatch — `embargo_release_date` is written only when a *governing* request exists; a deposit that merely requested `EMBARGOED` keeps it null while still recording `access_level` `EMBARGOED` — routes/deposits.py:107-124 (verified live)

**Pass C scanned and already fully pinned (no edit):** `services/clearance.py` — every item test, both variants, the `ITEM_ORDER` emission order, `latest_thesis_for_student` tie-break, `variant_for_term`, the five-branch `status_for` ladder, `cleared_at` set/preserve/reset, and the student mirror all match §3.9 line-for-line; the deliberate difference between §3.9's `PERMISSIONS` item (counts rows, tolerates `DEFICIENT` if the total is met) and §3.5/§3.8's `ERR_PERMISSIONS_INCOMPLETE` (every row must be `ACCEPTED`/`WAIVED`) is already distinctly pinned on both sides. `services/counters.py` — fully covered by §2.10 + §2.4; `recompute_all_chair_loads` re-derives for every faculty member rather than only affected chairs, but uses `reconcile`, so only rows whose value moved bump — unobservable versus §3.3's wording. `routes/deposits.py` handle sequencing — `(created_at, version, _seq)` ascending over `DEPOSITED` rows of the term already pinned by §3.8, including that a withdrawn deposit frees its sequence number.

**Pass C deliberately not edited (unreachable / unobservable):** `integrity.py:115-121` `REFER`'s second precondition (`thesis.integrity_state != "SCREEN_FLAGGED"` → `ERR_SCREENING_STATE_INVALID`) — a `FLAGGED` screening always coexists with a `SCREEN_FLAGGED` document, so the clause is unreachable. `thesis is None` fallbacks in permissions.py:110, embargo.py:110,192, integrity.py:94 and the `degree_level` default `"DOCTORAL"` at embargo.py:65 — nothing deletes rows. Clearance/student rows are also written twice in the integrity cascade (verified +2 each) but not universally — with two documents per candidate the projection's `reconcile` can be a no-op, so the PRD was left under-determined there rather than asserting a false universal.

**Hand-off notes resolved by pass C:**
- **Note 3 (`write` vs `reconcile`):** §3.6 step 2's wording survives intact — it makes no version claim. The observable consequence is one step later, so it was pinned on step 3 instead: `sync_thesis_counters` is a genuine second write on the document row whenever voiding a decided `REVISIONS_REQUIRED` cycle lowers `analyst_turnaround_bdays_total` (verified: thesis `version` +2, total 3 → 0), and no bump when only a `PENDING_REVIEW` cycle is voided.
- **Note 4 (selective counter writes):** no edit needed. `format_cycle_count` can only move on a format submission, `documented_permission_count` only on a permission create/review, `analyst_turnaround_bdays_total` only on a format submission/decision or the void step of the cascade — each route writes exactly the counters its own event can move, so every selective write is value-equivalent to a full `sync_thesis_counters`. §2.10's blanket "recomputed on the events described in §3.5 through §3.7" is accurate in effect even though §3.7 and §3.8 events write no counters at all; the only observable difference is the version bump, already pinned per-route.

### Step 9 totals and orchestrator verification

38 edits total (28 ambiguity-pins, 10 mismatch-revisions). `PRD_COMPLETED.md` is 416 lines / 102,126 bytes vs `PRD_FINALIZED.md` 416 lines / 91,946 bytes — **+10,180 chars, +11.07%**, all in-paragraph (line count unchanged, no new sections). Verified `cmp` that `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran) — 38 lines differ. Structural integrity intact after all three passes: still 5 top-level sections, still 47 endpoint rows in §4, still 50 error rows in §5, file still ends on a complete §5 table row. No pass touched `implementation/`, `test_suite/`, or `test_helpers/`, so Step 7's verified 8×101/101 sweep still stands.

## Pipeline complete — 2026-09-03T06:46:49.219Z

All nine steps finished. Final artifacts in place: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 modules), test_suite/ (18 modules, 101 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ (25 modules + start.sh) with results.{1..8}.json all at 101/101.
