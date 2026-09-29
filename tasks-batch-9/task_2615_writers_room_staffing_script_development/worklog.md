# Worklog — task_2615_writers_room_staffing_script_development

## Step 1: Create task directory — 2026-09-03T20:13:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2615_writers_room_staffing_script_development` and its `workspace/` subdirectory. Index 2615 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-03T22:08:00.000Z

The task-2615 scaffold package is complete and lint-clean.

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2615_writers_room_staffing_script_development/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2615_writers_room_staffing_script_development/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2615_writers_room_staffing_script_development/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  1797

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2615_writers_room_staffing_script_development/`)

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 3310 | `scenario`, `domain_name`, `api_prefix`, `response_envelope`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` (no `scaffold_*_design` keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2322 | `scaffold_difficulty_design` (only) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4766 | `scaffold_corner_design` (only) |

## Inventory

- §1.1–§1.7: 14 entities, 9 state machines, 4 OCC `concurrency_rules`, 14 calculations (2 dual-variant: `guarantee_settlement`, `credit_share_determination`), 38 validations, **61 endpoints**, 80 error codes, 5 roles.
- §1.8: **9 rule_ids / 20 instances** (`dual_variant_calc` 3, `combinatorial_formula` 3, others 2 each).
- §1.9: **9 sections / 92 instances** — entities 24, state_machines 15, calculations 16, validations 14, endpoints 5, errors 5, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1. Of these, 74 carry full `test_recipe`s and 18 are `excluded_because:` stubs citing §1.8 instances by name.
- All 112 instance names are unique across both design files; all 80 error codes are referenced by at least one instance (verified programmatically).

Notable fixes made while finishing §1.9: the entity-backed-RBAC instance was rebuilt around two rooms (an OFFERED seat and an ACTIVE room cannot coexist in one room, so the original chain was unreachable); the shared-operations instance gained a credit submission so the `close` call isn't refused by priority-74; the self-approval assert now accounts for `NOTES_ISSUED` satisfying the redelivery gate; and the stale `difficulty_level` comment in `SCAFFOLD.yaml` (claimed 60 endpoints / 44 errors / 8 calculations / 7 machines) was corrected to the real counts.

## Step 3: Copy shared files — 2026-09-03T22:09:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2615_writers_room_staffing_script_development/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T22:28:00.000Z

PRD generation for task 2615 is complete.

**Output:** `workspace/PRD.md` — **507 lines** (106,730 bytes), written incrementally (1 small `Write` + 8 `cat >>` heredoc/python appends, `wc -l` checked after each), so no 64k truncation. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Section outline (headings only)**

```
# Writers Room Staffing & Script Development API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
### 2.1. Identity, Roles and Access Control
### 2.2. API Response Structure
#### Standard Success Response Format
#### Standard Error Response Format
### 2.3. Pagination
### 2.4. Common Resource Properties
### 2.5. The Logical Production Clock
### 2.6. The Guild Agreement Rate Card
### 2.7. Money, Counting and Rounding Discipline
### 2.8. Interval and Calendar Semantics
### 2.9. Optimistic Concurrency Control on Rooms, Episodes and Seasons
### 2.10. Cascading Recomputation and Conserved Quantities
### 2.11. Path Resolution and Validation Precedence
## 3. Business Logic & Workflows
### 3.1. The Guild Rate Card, the Writer Registry and Availability
### 3.2. Opening a Season, Ordering Episodes and Rescheduling Photography
### 3.3. Configuring the Room and Offering Seats
### 3.4. Seat Responses, Release, and the Room's Operating Posture
### 3.5. Assigning Scripts: Fees, Guarantee Slots and the Fee Ledger
### 3.6. Delivery, Notes, Approval and the Void Path
### 3.7. Script Clearance for Names, Trademarks and Depictions
### 3.8. Script Coverage and the Production Lock
### 3.9. Credit Determination and Guild Arbitration
## 4. API Endpoints
## 5. Error Codes
```

**Verification (all mechanical, run against SCAFFOLD.yaml)**

- Endpoint coverage: **61/61** paths present, 0 missing. §4 table = 61 data rows, exactly 4 columns.
- Error coverage: **80/80** error ids present, 0 missing; **0 HTTP-status mismatches** against the scaffold. §5 table = 80 data rows, exactly 2 columns.
- Hard Contract 1 (Field-Name Coverage): **168/168** required identifiers (148 entity fields ∪ 101 endpoint input identifiers ∪ 14 path params) appear verbatim in backticks — 0 missing. Also 39/39 state names and 87/87 enum members present.
- Hard Contract 2 (Rule Coverage): all 9 state machines' transitions, all 14 calculations, all 38 validations (with the numbered precedence list in §2.11), all 4 OCC rules (write endpoint + `expected_*_version` + error + 412), and the three named cascades / three conservation identities are documented.
- Hard Contract 3 (§3 Path Purity): 311 backticked tokens in §3 scanned — **0** start with `/`, **0** are bare HTTP methods, **0** are method+path pairs; also 0 unbackticked raw paths or method+path strings in §3. All HTTP paths live in §2.9 and §4.
- §2.2 is byte-verbatim from `section-2.2-response-structure.md`.
- File ends at a real boundary: the final line is the last `ERR_SCRIPT_COVERAGE_INSUFFICIENT` row of the §5 table; no audit footer, no mid-sentence/mid-table truncation.

**Scaffold contradictions resolved deliberately** (consistently applied throughout): `risk_weight` is 0 while a `ClearanceItem` is `SUBMITTED` (entity + calculation over the endpoint side-effect line); issue-notes leaves the assignment in `IN_NOTES` (state machine over the endpoint line) while still applying the `READY → IN_PROGRESS` + coverage recompute; reconfigure re-derives `CONFIRMED` seats only; seat release keeps `room_seat_id` on the assignment; assignment seat selector ranks `confirmed_at` ASC then `created_at` ASC; `outcome` is `UPHELD` when the arbitrated map equals `provisional_credit_shares`; `receives_credit` is written at close from the provisional share and re-evaluated at determination, with `on_screen_credit_count` moving only at determination; clearance-review creation sets the episode mirror to `PENDING` (where it already sits) and later posture changes mirror only for the `approved_teleplay_assignment_id` review.

**Orchestrator truncation check (per invocation directive):** `tail -12 workspace/PRD.md` confirms the file ends with the final `ERR_SCRIPT_COVERAGE_INSUFFICIENT | 409` table row — a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T23:07:00.000Z

Implementation complete for task 2615.

## File inventory (`.../task_2615_writers_room_staffing_script_development/workspace/implementation/`)

| file | lines |
|---|---|
| `requirements.txt` | 1 |
| `start.sh` | 10 |
| `app.py` | 80 |
| `db.py` | 127 |
| `errors.py` | 186 |
| `middleware.py` | 66 |
| `response.py` | 113 |
| `validation.py` | 216 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 179 |
| `services/domain.py` | 467 |
| `routes/__init__.py` | 0 |
| `routes/common.py` | 35 |
| `routes/agreements.py` | 103 |
| `routes/writers.py` | 120 |
| `routes/seasons.py` | 96 |
| `routes/rooms.py` | 148 |
| `routes/seats.py` | 213 |
| `routes/episodes.py` | 110 |
| `routes/assignments.py` | 240 |
| `routes/milestones.py` | 73 |
| `routes/clearance.py` | 159 |
| `routes/credits.py` | 282 |
| `routes/ledger.py` | 29 |
| `routes/clock.py` | 18 |
| **total** | **3071** |

Every module passes `python3 -m py_compile`; `__pycache__` dirs removed.

## Endpoint coverage: 61 / 61

I diffed the live Flask url_map (method + path with `{}`-normalised variables) against every endpoint declared in SCAFFOLD §1.5: `declared 61, implemented 61, MISSING: [], EXTRA: []`.

## Smoke test (port 51615, killed by the listening PID only — never a broad pkill)

Ran a 60-call end-to-end script through a fresh `PORT=51615 bash start.sh` boot; **0 failures**, all statuses as expected. Covered: clock set → agreement → 2 writers (level walk `22 credits → PRODUCER`, `5 → STORY_EDITOR`, award 10 → `CO_PRODUCER`) → duplicate member id 409 → availability window → season → room open/open-staffing/activate → seat offer (guild floor 700000 beat the 750000 offer; prorated 21 weeks × 750000 + 6 × rhu(750000/7) = 16,392,858 ✔) → stale-version 412 → accept (window `CONSUMED`, two-way link) → episode → `STORY_AND_TELEPLAY` assignment (gross 5,000,000) → 3 synthesized milestones with correct chain, `sequence_index` 1..3 and due dates at `23:59:59.999Z` (`2026-05-01/11/21`, i.e. production start 2026-06-10 minus 40/30/20 days) → deliver all three → assignment `DELIVERED` → clearance review + item + `ERR_CONDITIONAL_NOTE_REQUIRED` 422 → `CONDITIONAL` decision (risk 10) → waiver → approve (readiness `READY`, credit `SUBMISSIONS_OPEN`, ledger `SCRIPT_FEE_ACCRUAL +5,000,000` then `GUARANTEE_REALLOCATION −2,500,000` from chronological settlement) → credit submission + `ERR_DUPLICATE_SUBMISSION` 409 → close (provisional 100) → 3-arbiter panel (participants ordered, `STATEMENTS_OPEN`) → `ERR_VOTE_SHARES_INVALID` 422 → 3 ballots (concurrence 1.0) → determine (`UPHELD`, credit string "Bo Pen", episode `DETERMINED`) → post-approval clearance review mirrored `CLEARED` onto the episode → lock (`LOCKED`, `locked_at` from the logical clock) → season coverage `1 / gap 0 / COVERED`, staffing commitment 760,000 (= 750,000 subtotal + rhu(TIER_1 100,000 × 0.1 IN_PERSON surcharge) ✔), fees 2,500,000 → seat release cascade B (seat `RELEASED`, window back to `OPEN`). Envelope negatives also verified: unknown role 401, 404 not-found, `ERR_INVALID_PAGINATION` 400, `ERR_ROLE_NOT_PERMITTED` 403, unknown route 404 in the error envelope.

Two behaviours worth flagging (both follow PRD prose literally): the episode clearance mirror only fires when `review.assignment_id == episode.approved_teleplay_assignment_id`, so a review waived *before* approval leaves the episode at `PENDING` and blocks the lock until a posture change occurs on the approved teleplay; and opening a new review sets the episode's `clearance_posture` to `PENDING` unconditionally.

Storage is in-memory only (verified: no `sqlite`/`json.dump`/`open(`/`/tmp`/`pickle` anywhere), and a fresh boot has 0 rows in every listable table with the logical clock at exactly `2026-08-01T00:00:00Z`. No smoke server is left running (port 51615 free).

## Step 5: Generate unit tests — 2026-09-04T00:54:35.000Z

The suite is complete. Both remaining modules are written, and the whole-suite audits pass.

## File inventory (all at the task root, nothing under `workspace/`)

`test_helpers/` — 2787 lines
| file | lines |
|---|---|
| `__init__.py` | 64 |
| `api_client.py` | 363 |
| `api_errors.py` | 222 |
| `assertions.py` | 272 |
| `constants.py` | 228 |
| `factories.py` | 277 |
| `fixtures.py` | 981 |
| `test_users.py` | 135 |
| `types.py` | 445 |

`test_suite/` — 9270 lines, 114 tests
| file | lines | tests |
|---|---|---|
| `conftest.py` | 29 | — |
| `test_01_guarantee_and_credit_variants.py` | 288 | 6 |
| `test_02_combinatorial_formula.py` | 238 | 6 |
| `test_03_state_machines.py` | 194 | 4 |
| `test_04_cascades.py` | 244 | 4 |
| `test_05_priority_conflicts.py` | 244 | 4 |
| `test_06_boundaries.py` | 283 | 4 |
| `test_07_cross_entity_state.py` | 243 | 4 |
| `test_08_temporal_overlap.py` | 291 | 4 |
| `test_09_compensating_invariants.py` | 242 | 4 |
| `test_10_entities.py` | 1557 | 24 |
| `test_11_state_machines.py` | 907 | 12 |
| `test_12_calculations.py` | 566 | 7 |
| `test_13_validations.py` | 1030 | 12 |
| `test_14_endpoints.py` | 597 | 5 |
| `test_15_errors.py` | 713 | 5 |
| `test_16_rbac.py` | 662 | 6 |
| `test_17_complexity_layers.py` | 510 | 2 |
| `test_18_consistency.py` | 232 | 1 |

## Coverage against the design indices

- **Total: 114 tests, 438 PRD citations, 0 non-verbatim.**
- **Queue A (§1.8 Difficulty): 20 live instances, 0 stubs → 40 tests** (exactly 2 per instance; no instance under 2).
- **Queue B (§1.9 Corner): 74 live instances + 18 `excluded_because:` stubs → 74 tests** (1 per live instance). Live per section: entities 24, state_machines 12, validations 12, calculations 7, rbac 6, endpoints 5, errors 5, cross_cutting_complexity_layers 2, consistency_model 1.
- Structural audit: every live instance covered exactly once (queue B) or twice (queue A); **0 uncovered live instances; 0 tags pointing at stubs or unknown names; 0 untagged tests; 0 dual-tagged tests**; every `Design:` line's rule_id/section prefix matches the instance's real location in the yaml; the tag is the last line of every docstring.
- `pytest --collect-only` collects **114 tests** cleanly; `py_compile` and `pyflakes` are clean across `test_suite/` and `test_helpers/` (I removed three genuinely unused imports left in modules 01–03).

## SKIPPED instances

**None.** Every live instance in both indices survived the PRD-first filter. Where the design contradicted the PRD I asserted the PRD and dropped the offending sub-claim rather than the instance — the ones relevant to this session's two modules:

- `ERR_WRITER_NOT_STAFFED`: the corner design says 422; the PRD error table (line 500) says **409**. Test 17 asserts 409.
- The stale-offer race: the design calls the competing availability check "priority 66"; the PRD's list numbers OCC 13 and structural containment 18. Same outcome (`ERR_STALE_ROOM_VERSION`, 412), comment reworded to the PRD's numbering.
- Error-envelope shape: the design repeatedly writes `{error: {id, message}}`; PRD §2.2 puts `error_id`/`message` inside `data` with `response_type: "error"`. All modules assert the PRD shape.

## Notes for the caller

- The suite has **never been executed against an implementation** — no server was started and no sweep was run, so this is a static-validation result only. `workspace/` was not touched (`INSTRUCTION.md`, `PRD.md`, `implementation/` only), and no `pkill` of any kind was issued.
- Two new modules this session: `test_17_complexity_layers.py` (the four OCC races in one sequence; the `confirmed_at`-ordered seat selector with the frozen-at-creation reference) and `test_18_consistency.py` (the acceptance response already carrying `prorated_commitment_cents` 15514284 and the room/season/writer/window reads agreeing immediately, plus the single-resource vs list envelope distinction).

## Step 7: Run tests and iterate — 2026-09-04T01:25:30.000Z

All 8 parallel rounds pass 114/114.

## Summary

**Iterations run:** 2 (iteration 1 = baseline, 102/114 in all 8 rounds with an identical 12-test failure set — no flakiness anywhere; iteration 2 = clean 114/114 in all 8 rounds).

**Tests deleted:** none. Every failure traced to a test-layer defect, not to PRD silence.

**Fixes applied to `test_helpers/`:** none needed — no fixture or factory built a precondition inconsistent with the PRD. (`test_helpers/api_errors.py` already carried the correct 409 for `ERR_WRITER_UNAVAILABLE`; the wrong status was hardcoded at the call site.)

**Fixes applied to `test_suite/`** (all 12 failures; each fix makes the assertion more faithful to a verbatim PRD sentence):

- `test_04_cascades.py`
  - `test_pulling_the_production_start_in_flips_two_milestones_late`, `test_pushing_the_production_start_out_again_un_flips_the_lateness`: compared `production_start_date` against the bare input spelling `...T00:00:00Z`. PRD §2.4: "Timestamps are ISO 8601 UTC strings with exactly three fractional-second digits." Switched to the existing `A.assert_instant` helper so the comparison is on the instant, not its spelling.
  - `test_releasing_a_seat_frees_the_window_and_parks_the_assignment`: asserted `room_seat_id=None` after release. PRD §3.4: "the assignment keeps the seat reference it was created with". Now asserts the seat id.
  - `test_releasing_a_seat_collapses_the_room_burn_and_the_season_commitment`: setup re-offered a seat into an `ACTIVE` room, which PRD correctly refuses with `ERR_ROOM_NOT_ACCEPTING_SEATS`. Removed that trailing un-PRD-covered re-offer block; the conserved-counter assertions (all PRD-covered) stay.
- `test_08_temporal_overlap.py` / `test_15_errors.py` (`test_the_buffer_reaches_backwards_...`, `test_every_uniqueness_and_capacity_ceiling_...`): both asserted `ERR_DUPLICATE_EPISODE_NUMBER` on a request that also violated production-unit turnaround. PRD §2.11 step 18 lists "production-unit turnaround" **before** "capacity and uniqueness", so `ERR_PRODUCTION_UNIT_CONFLICT` reports first. Moved the duplicate-number reuse onto `UNIT_B` so uniqueness is the sole violation — the rule under test is now isolated rather than the assertion weakened. (test_08's function renamed accordingly.)
- `test_09_compensating_invariants.py` (`test_the_void_returns_the_guarantee_slot_and_freezes_the_milestones`): asserted `ERR_MILESTONE_NOT_DELIVERABLE` for a delivery against a still-`PENDING` milestone of a `VOID` assignment. The test's own cited PRD quote says the block comes from the assignment gate — "because delivery requires the owning assignment to be in `DRAFTING` or `IN_NOTES`" — so corrected to `ERR_ASSIGNMENT_NOT_DRAFTING`.
- `test_10_entities.py` / `test_15_errors.py` (`test_convening_the_panel_...`, `test_the_credit_workflow_...`): asserted `ERR_ARBITRATION_ALREADY_EXISTS` on a second convene. After the first convene the episode is `IN_ARBITRATION`, and the credit-status gate is a §2.11 step-14 state check while at-most-one-arbitration is step-18 uniqueness, so `ERR_ARBITRATION_NOT_AVAILABLE` reports first (PRD §3.9 also names the status check first in the same sentence).
- `test_14_endpoints.py`
  - `test_reconfigure_rewrites_every_confirmed_seat_...`: called `A.assert_seat_pricing(prorated=...)` — the helper's parameter is `prorated_commitment_cents`. Fixed at 3 call sites (a plain `TypeError`, not a domain claim).
  - `test_offering_a_seat_links_a_writer_a_room_and_the_window_that_covers_it`: hardcoded `expected_status=422` for `ERR_WRITER_UNAVAILABLE`; PRD §5 binds it to 409. Fixed.
  - `test_season_and_ledger_reads_return_the_calculated_figures_not_stored_copies`: compared `A.entry_types(...)` (a list) against a set literal, so it could never hold. Replaced with the ordered list PRD states verbatim — `SCRIPT_FEE_ACCRUAL` then `GUARANTEE_OFFSET`.

**Fixes applied to `implementation/`:** none. Every one of the 12 failures was the implementation being right and the test being wrong; no PRD-required check was removed or weakened, and no endpoint/field/side-effect was added.

### Orchestrator verification of the Step 7 sweep artifacts

The Step 7 subagent exited claiming a clean 8-round sweep, but left **no `results.*.json` and no `sweep.log`** in `workspace/` — the claim had no artifacts behind it (a known failure mode for this step). The orchestrator therefore re-ran the full 8-round sweep itself under `setsid nohup` (launched 2026-09-04T01:16:06Z, complete by 01:25:30Z) and read all 8 per-round JSON files directly:

```
round 1: 114 / 114 failed= 0
round 2: 114 / 114 failed= 0
round 3: 114 / 114 failed= 0
round 4: 114 / 114 failed= 0
round 5: 114 / 114 failed= 0
round 6: 114 / 114 failed= 0
round 7: 114 / 114 failed= 0
round 8: 114 / 114 failed= 0
```

Zero failures, zero errors, zero skips across all 8 rounds. The Step 7 result is confirmed on artifacts the orchestrator produced and inspected itself; `results.{1..8}.json` are now present in `workspace/implementation/`.

**Step 8 skip condition NOT met** (12 `test_suite/` fixes, so Step 7 ran beyond baseline) → Step 8 will run.

## Step 8: Finalize PRD — 2026-09-04T01:36:37.000Z

Both edits are in place. Summary:

## Line counts
- `PRD.md`: 507 lines / 106,730 bytes
- `PRD_FINALIZED.md`: 507 lines / 107,342 bytes
- Line delta: 0 (0.0%); byte delta +612 (+0.57%). Two sentences appended inline; no sections, no restructuring.

## Changes
- **§3.2 (Production-unit turnaround)** — insert — pinned the intra-step-18 sub-order: the turnaround test is evaluated ahead of the episode-number uniqueness test, so a request violating both reports `ERR_PRODUCTION_UNIT_CONFLICT`, not `ERR_DUPLICATE_EPISODE_NUMBER` — `implementation/routes/episodes.py:45-56`.
- **§3.9 (Convening arbitration)** — insert — pinned that the `credit_status` gate (§2.11 step 14) is applied before the at-most-one-arbitration uniqueness rule (step 18), so a second convene on an episode already `IN_ARBITRATION` reports `ERR_ARBITRATION_NOT_AVAILABLE` — `implementation/routes/credits.py:110-114`.

## Per-edit pre-edit search log
**Edit 1** — (a) Subject: relative evaluation order of the production-unit turnaround check and episode-number uniqueness on episode creation, plus anything else that consumes either rule. (b) Enumerated/read: `routes/episodes.py` `create_episode` (both loops; also the two step-7 `ERR_INVALID_REQUEST` guards for `episode_number > episode_order` and `production_start_date < season start` that precede both), `shoot_window()`, `services/domain.py::episodes_of`, `services/domain.py::reschedule_season` (shifts episode dates and does **not** re-run any turnaround check), and a repo-wide grep for `ERR_PRODUCTION_UNIT_CONFLICT` / `ERR_DUPLICATE_EPISODE_NUMBER` confirming a single raise site each. (c) Adjustment: scoped the sentence to episode creation and to the pairwise turnaround-vs-uniqueness comparison only — it makes no claim about the step-7 schema guards that fire earlier, and no claim that reschedule re-validates turnaround.

**Edit 2** — (a) Subject: precedence among the convene-panel guards, specifically credit-status state vs at-most-one-arbitration uniqueness. (b) Enumerated/read: `routes/credits.py::convene_panel` (arbiter-id existence → `v_id_list` size → status → uniqueness → distinctness/participation → eligible-submission), `close_submissions` and `determine`/`_finalize` (the only writers of `credit_status`: `SUBMISSIONS_CLOSED`, `IN_ARBITRATION`, `DETERMINED`), `cast_ballot` (leaves status `IN_ARBITRATION`), `domain.eligible_submissions`, and a repo-wide grep for both error codes confirming single raise sites. (c) Adjustment: left the original at-most-one sentence verbatim and added only the ordering claim; deliberately avoided asserting whether `ERR_ARBITRATION_ALREADY_EXISTS` is reachable (in the current impl the status check pre-empts it, but the check exists and PRD's original wording should stay intact).

## Items judged already PRD-determined (no edit)
- Timestamp spelling of `production_start_date` (`...T00:00:00.000Z`) — §2.4 "exactly three fractional-second digits"; `response.py::iso3` applies it to every datetime field.
- Assignment keeps `room_seat_id` after seat release — §3.4 verbatim; `domain.release_seat` never clears it.
- Re-offering a seat into an `ACTIVE` room → `ERR_ROOM_NOT_ACCEPTING_SEATS` — §3.3/§3.4; `seats.py:61`.
- `ERR_ASSIGNMENT_NOT_DRAFTING` for delivery against a `PENDING` milestone of a `VOID` assignment — §3.6 (`PENDING` is a deliverable status, so the assignment gate is the first failing check); `milestones.py:29-32`.
- `ERR_WRITER_UNAVAILABLE` = 409 — §5 table; `errors.py`.
- Ledger entry order `SCRIPT_FEE_ACCRUAL` then `GUARANTEE_OFFSET` — §3.5 append order + §2.3 `created_at` ascending; `domain.append_ledger` / `db.created_order` (insertion sequence only ever breaks exact-timestamp ties, which the impl does not produce since each row takes its own `wall_now()`).
- `assert_seat_pricing(prorated=...)` keyword and the list-vs-set comparison — pure test-layer defects with no PRD surface.

**Orchestrator note:** verified `PRD_FINALIZED.md` exists at 507 lines / 107,342 bytes and differs from `PRD.md` (+612 bytes), so the finalizer genuinely edited rather than copying. Step 9 will be run as three sequential file-partitioned passes over `implementation/` to prevent the known failure mode where a single-pass scan silently returns a byte-identical copy.

## Step 9: Complete PRD — 2026-09-04T02:10:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` (orchestrator decision, per the known failure mode where a single-pass scan returns a byte-identical copy). Each pass edited `workspace/PRD_COMPLETED.md` in place with targeted Edit calls; pass 1 created it from `PRD_FINALIZED.md`.

Net result: **507 → 507 lines, 107,342 → 122,623 chars (+15,281), 46 changed lines, 50 edits total (33 ambiguity-pins, 17 mismatch-revisions)**. Headings byte-identical to `PRD_FINALIZED.md` (28 sections, none lost); file ends at the §5 error table's last row (`ERR_SCRIPT_COVERAGE_INSUFFICIENT`).

### Pass 1 — app.py, db.py, errors.py, middleware.py, response.py, validation.py, routes/common.py, routes/clock.py, services/calc.py

12 edits (11 ambiguity-pins, 1 mismatch-revision). 107,342 → 112,023 chars.

- **§2 preamble** — insert — ambiguity — state is process-memory only and nothing is seeded at startup; the logical clock is the sole pre-set value — `app.py:1-6`, `db.py:1-5,54-83`
- **§2.1** — insert — ambiguity — a whitespace-only auth header counts as empty, and both header values are stripped before any later check reads them — `middleware.py:37-43`
- **§2.2 (`api_request_id`)** — insert — ambiguity — `req_` followed by exactly twenty characters from `A`–`Z` and `0`–`9` — `response.py:10,25-26`
- **§2.2 (`api_request_timestamp`)** — insert — ambiguity — read from real server time, not the logical clock — `response.py:32`
- **§2.3 (pagination)** — insert — ambiguity — each param is whitespace-stripped and parsed as a base-ten integer, so `10.5`, an empty value or non-numeric text fail; an omitted param takes its default — `response.py:86-107`
- **§2.3 (ordering + filters)** — insert — ambiguity — `created_at` ties fall back to server insertion order (agreements list is that order exactly reversed; `sequence_index` ties likewise); filters are exact-equality, never validated, so an unknown enum/id yields an empty page, boolean filters accept `true/1/false/0` case-insensitively and match nothing otherwise, integer filters that don't parse match nothing — `db.py:118-119`, `routes/common.py:7-23`, `validation.py:190-216`
- **§2.4** — insert — ambiguity — timestamps truncate (not round) below the millisecond; `created_at`/`updated_at` come from wall time while `confirmed_at`/`approved_at`/`delivered_at`/`locked_at` come from the logical clock; inbound ISO-8601 parsing accepts `T` or a space, optional seconds, 1–9 fractional digits, honours/normalises `Z` and `±HH:MM`, reads an offset-less value as UTC, and accepts a bare `YYYY-MM-DD` as midnight UTC — `response.py:13-22`, `db.py:17-51,94-115`
- **§2.5** — insert — ambiguity — `to_iso8601` is required (else `ERR_INVALID_REQUEST`), any instant forwards or backwards is accepted, the call returns HTTP 200 with an empty `data`, and no read-back endpoint exists — `routes/clock.py:12-18`
- **§2.11 (body-referenced ids)** — insert — ambiguity — a non-string id draws the resource's not-found code rather than a schema error — `middleware.py:59-66`
- **§2.11 step 7** — insert — ambiguity — explicit `null` is treated as absent; a missing/empty/unparseable body is the empty object while a non-object body fails outright; booleans are never numbers and integer fields reject whole floats (number fields accept ints); undeclared top-level fields are ignored — `validation.py:14-31,39-121`
- **§3.9 step 5** — insert — ambiguity — remaining tie among submissions sharing a `created_at` broken by insertion order — `services/calc.py:145`, `routes/credits.py:77-79`
- **§5** — revise — mismatch — the table was declared to list *every* error the API may return, but the app also emits three envelope-level codes: `ERR_NOT_FOUND` (404, unrouted path), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500), all in the same error envelope — `app.py:57-70`
- **§4 preamble** — insert — ambiguity — trailing slash is tolerant (`/writers` ≡ `/writers/`) — `app.py:35`

Judged already pinned and correct: the whole 80-id error catalogue (programmatic diff of `errors.py::ERROR_STATUS` vs the §5 table — identical ids and statuses, no drift); envelope shape; pagination mechanics (defaults 10/0, bounds 1–100 / ≥0, `ERR_INVALID_PAGINATION` 400, post-filter/pre-slice `total_count`, `has_more`); common properties incl. the ledger-entry projection exception; auth/RBAC precedence steps 1→4 with 401/401/403/403; the clock default `2026-08-01T00:00:00Z`; strict `end > start` intervals; and every formula in `services/calc.py` (level threshold walk, guild floor single-rounding, capped diversity subsidy, daily-rate-first proration, four-step room burn, script fee, largest-remainder shares, risk weight and the capped escalation ladder, due-date lead days at `23:59:59.999Z`, milestone chains, `rhu_places(…, 3)` concurrence).

### Pass 2 — routes/agreements.py, writers.py, seasons.py, rooms.py, seats.py, episodes.py

15 edits (9 ambiguity-pins, 6 mismatch-revisions). 112,023 → 116,969 chars. All 12 pass-1 edits verified still present.

- **§2.4** — revise — mismatch — the universal "each mutated row's own `version` increments" was false for two rows; pinned that a `Season`'s `staffing_commitment_weekly_cents` / `script_fee_committed_cents` / `ready_script_count` / `coverage_gap` / `coverage_posture` and a `Writer`'s `active_seat_count` / `on_screen_credit_count` are rewritten in place with `updated_at` and `version` frozen, season version advancing only on reschedule and writer version only on the credit award — `routes/seats.py:106,177-178`, `services/domain.py:300-301`, `routes/credits.py:194`, `services/domain.py:100-132,366`, `routes/writers.py:68`
- **§2.6** — insert — ambiguity — duplicate `mba_year` has no dedicated code and fails with `ERR_INVALID_REQUEST`, and because it is the last check, a request that both repeats a year and breaks a field/ordering rule reports the field problem — `routes/agreements.py:83-86`
- **§3.1 credit award** — insert — ambiguity — `episodic_credits_awarded` is a required integer of at least 1 (0 is a schema failure), and `agreement_id` is required here too — `routes/writers.py:60-63`
- **§3.1 availability** — revise — mismatch — the old prose gave `commitment_type` behavioral meaning; pinned that it is stored and read by no rule, rationing coming solely from the `OPEN`→`CONSUMED` lifecycle, and that the seat's own `exclusivity` is the field the collision rule reads — `routes/writers.py:96`, `routes/seats.py:83`
- **§3.1 availability** — insert — ambiguity — window creation applies no ownership check; an acting `Writer` may lodge a window on another writer's record and `ERR_NOT_RESOURCE_OWNER` never arises — `routes/writers.py:88-91`
- **§3.2 episode ordering** — insert — ambiguity — an `episode_number` above `episode_order` and a `production_start_date` before the season's both yield `ERR_INVALID_REQUEST`, never `ERR_INVALID_DATE_RANGE`; an episode has no `end_date` so no start-before-end test — `routes/episodes.py:34-35,41-42`
- **§3.3** — insert — mismatch — §2.1's blanket "showrunner authority is scoped to the season" does not hold for the room/seat surface; pinned that room create, open-staffing, seat offer, withdraw, release and wrap never compare the actor to `showrunner_writer_id` — `routes/rooms.py:20,59,120`, `routes/seats.py:34,163,187`
- **§3.3** — insert — ambiguity — the room `start_date` span is inclusive at both ends and a violation is `ERR_INVALID_DATE_RANGE`; `end_date` has no upper bound; `duration_weeks_committed` is never reconciled against the date span — `routes/rooms.py:34-37`
- **§3.3 seat-offer guards** — revise — mismatch — PRD had room status before version; impl (and §2.11 step 13 < 14) check `ERR_STALE_ROOM_VERSION` first — `routes/seats.py:58-62`
- **§3.4 acceptance** — revise — mismatch — PRD listed seat state before ownership; impl checks `ERR_NOT_RESOURCE_OWNER` first per §2.11 step 11 — `routes/seats.py:123-129`
- **§3.4 window selection** — insert — ambiguity — insertion-order tie-break after `start_date`/`created_at`; `commitment_type` plays no part in the ranking — `routes/seats.py:24-29`
- **§3.4 decline** — insert — ambiguity — `reason` is 1–500 characters when supplied, on the same terms for decline/withdraw/release, and is validated but never stored or echoed — `routes/seats.py:153,167,191`
- **§3.4 reconfigure** — revise — mismatch — PRD said every re-derived seat's version increments; impl bumps the room unconditionally but a seat only when one of its five figures actually changed — `services/domain.py:326-334`
- **§3.8 production lock** — insert — mismatch — the "first gate is `ERR_EPISODE_NOT_READY`" claim contradicted the locked hard stop; an already-`LOCKED` episode reports `ERR_EPISODE_ALREADY_LOCKED` ahead of the readiness gate — `routes/episodes.py:77-80`
- **§4 endpoint table** — revise — ambiguity — `GET /guild-agreements` documented as filterable by `mba_year`; `GET /seasons` filter list extended with coverage posture — `routes/agreements.py:102`, `routes/seasons.py:95`

Judged already pinned and correct: agreement field types/ranges/defaults, ordering-constrained maps, strict lead-day decrease, immutability and newest-first listing; writer registration incl. duplicate `guild_member_id` 409 and the inclusive descending threshold walk with multi-level jumps; window `OPEN`/`consumed_by_seat_id` lifecycle and containment; season creation, showrunner-eligibility as `ERR_INVALID_REQUEST`, staffing-window ordering as `ERR_INVALID_DATE_RANGE`, zeroed counters, `guarantee_application_mode` default; reschedule version gate then `ERR_RESCHEDULE_DATE_INVALID`, locked-episode freeze, cascade order, season version bump; room enums/ranges, `diversity_seats_required ≤ capacity`, `ERR_MINI_ROOM_SEAT_LIMIT` on create and reconfigure, `TIER_1` at birth; open-staffing gate and `ERR_STAFFING_WINDOW_CLOSED` boundary; the five activation gates in order with the re-tested budget; wrap gate and `WRAPPED` exclusion from the commitment sum; the full seat-offer guard chain after the version/state swap; all seat money derivations; acceptance side effects and the two-way window link; decline/withdraw terminality and counter arithmetic; the release chain; episode initial state and create-time coverage recompute; the production-unit turnaround inequality and its precedence over `ERR_DUPLICATE_EPISODE_NUMBER`; lock roles, `ERR_NOT_SEASON_SHOWRUNNER`, the two-code clearance gate, the inclusive coverage gate, `locked_at` from the logical clock; all §4 role lists for the 25 endpoints in the partition and every §5 code/status they raise.

### Pass 3 — routes/assignments.py, milestones.py, clearance.py, credits.py, ledger.py, services/domain.py

23 edits (16 ambiguity-pins, 7 mismatch-revisions). 116,969 → 122,623 chars. Passes 1 and 2 verified intact (distinctive markers from both spot-checked, each exactly one hit).

- **§2.11 step 14 note** — revise — mismatch — the "any write against a `LOCKED` episode" universal narrowed to the only four gated writes (assignment create, void, milestone deliver, re-lock) and explicitly excludes issue-notes/approve/clearance/credits — `routes/assignments.py:59,197`, `routes/milestones.py:33`
- **§2.11 step 11** — insert — mismatch — panel membership (`ERR_ARBITER_NOT_ON_PANEL`) evaluated at the ownership position, ahead of arbitration state — `routes/credits.py:171`
- **§2.11 step 19** — revise — mismatch — "panel membership" removed from the referential-rules step — `routes/credits.py:171`
- **§3.2 reschedule** — insert — ambiguity — delivered/notes-issued/accepted milestones keep status and frozen `days_late` (only `due_date` moves); every shifted episode, non-void assignment and milestone bumps `version` unconditionally — `services/domain.py:346-364`
- **§3.5 guarantees** — insert — ambiguity — a create writes settlement only onto the new assignment; a slot freed by a `FORWARD_COMMIT` void can sit unclaimed forever — `routes/assignments.py:90-95`, `services/domain.py:203-216`
- **§3.5 creation state** — revise — mismatch — `late_milestone_count` is recomputed from freshly synthesized milestones, so it is non-zero when deadlines already passed (PRD had claimed always 0) — `routes/assignments.py:108-109`
- **§3.6 delivery** — insert — ambiguity — assignment `version` moves only when the delivery changed its status or late count — `routes/milestones.py:44-56`
- **§3.6 notes** — revise — ambiguity — `notes` is 1–4,000 chars, validated but never stored or echoed — `routes/assignments.py:128`
- **§3.6 notes** — revise — ambiguity — episode `version` moves only in the `READY` case; moved milestones bump their own — `routes/assignments.py:138-145`
- **§3.6 approval settlement** — revise — ambiguity — a re-settled assignment bumps `version`; `GUARANTEE_REALLOCATION` is appended only when the payable delta is non-zero — `services/domain.py:251-264`
- **§3.6 approval settlement** — insert — ambiguity — no fiscal ceiling is re-tested on a reallocation — `routes/assignments.py:177-180`
- **§3.6 void** — revise — mismatch — `reason` is 1–500 chars and not stored; **no season-scope test**, so `ERR_NOT_SEASON_SHOWRUNNER` never arises on void — `routes/assignments.py:188,194`
- **§3.6 void** — revise — ambiguity — episode `version` moves only on the `IN_PROGRESS → NOT_STARTED` fallback — `routes/assignments.py:215-219`
- **§3.7 review open** — revise — ambiguity — episode posture reset to `PENDING` whatever assignment the review names and even when locked, applied (with version/coverage) only when the posture differed — `routes/clearance.py:52-55`
- **§3.7 mirror** — insert — ambiguity — mirror writes only on an actual change; several reviews per assignment allowed, last mover wins — `services/domain.py:381-391`
- **§3.7 decide** — revise — ambiguity — `conditional_note` is 1–500 chars — `routes/clearance.py:92`
- **§3.7 decide** — revise — ambiguity — the parent review's `version` also increments on every decision — `routes/clearance.py:105`
- **§3.7 waiver** — revise — ambiguity — `waiver_memo` is 1–1,000 chars — `routes/clearance.py:117`
- **§3.8 coverage** — revise — mismatch — trigger enumeration extended with issue-notes, the reschedule chain, review open, item raise, season creation and episode order — `routes/clearance.py:55,79`, `routes/assignments.py:145`, `services/domain.py:365`
- **§3.9 close** — insert — ambiguity — responds with the updated episode; every classified submission bumps `version` — `routes/credits.py:91-95`
- **§3.9 ballot** — insert — ambiguity — absent/null/non-object `vote_shares` → `ERR_INVALID_REQUEST`; the structural check precedes membership/state/duplicate — `routes/credits.py:155-169`
- **§3.9 determine** — insert — ambiguity — `POLICY_REVIEW` yields `ERR_ARBITRATION_CLOSED` without the override and `ERR_POLICY_OVERRIDE_NOT_APPLICABLE` with it — `routes/credits.py:219,232`
- **§3.9 credit string** — revise — ambiguity — null (not empty) when no writer holds credit — `services/domain.py:467`

Judged already pinned and correct: script-fee derivation and the create-time budget test on `payable_fee_cents`; both guarantee modes' candidate orders and tie-breaks; the four ledger entry types, signs, and the void's negate-the-sum reversal; §2.10's conserved-quantity identities; `_select_seat`'s `confirmed_at → created_at` ranking; type-exclusivity and predecessor-linkage guards; all-four-due-dates population and per-type milestone chains with `PENDING`/`LATE` birth status; delivery's fixed order, `days_late` flooring and the `DRAFTING → DELIVERED → IN_NOTES → DRAFTING` loop; the revision cap; approval's ordering of season-scope → state → self-approval, `approved_by_role`, teleplay-only readiness advance and first-approval credit opening; the clearance risk-weight/multiplier table, the 100-cap and the five-rung ladder incl. waiver stickiness; coverage's two-dimension count, gap floor and posture bands; the six-step share normalisation at both close and determination; arbiter distinctness/interest disqualification; panel means, leading writer, concurrence rounding and the inclusive threshold; `UPHELD`/`REVISED`; the policy-override fallback; `on_screen_credit_count` moving only at determination; and the ledger read endpoint's roles, filters, ordering and `id`/`created_at`-only projection.

### Orchestrator verification

- `PRD.md` 507 lines / 106,730 chars → `PRD_FINALIZED.md` 507 / 107,342 → `PRD_COMPLETED.md` 507 / 122,623.
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md`; `diff` reports 46 changed lines (92 diff lines).
- `diff` of all `^#` lines between the two files is empty — no section added, removed or renamed.
- `tail` confirms the file still ends at the §5 error table's final row (`ERR_SCRIPT_COVERAGE_INSUFFICIENT | 409`), a real boundary.
- `implementation/` was not touched after the Step 7 verification sweep, so `results.{1..8}.json` (114/114 × 8) remain the valid final evidence.

**Pipeline complete.**
