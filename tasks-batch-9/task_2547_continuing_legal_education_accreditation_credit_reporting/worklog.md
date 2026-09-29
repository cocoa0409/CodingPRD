# Worklog — task_2547_continuing_legal_education_accreditation_credit_reporting

## Step 1: Create task directory — 2026-09-03T09:12:34.959Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2547_continuing_legal_education_accreditation_credit_reporting` and its `workspace/` subdirectory. Index 2547 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed and no index was auto-allocated (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T11:39:11.841Z

All three scaffold artifacts are complete and the linter is clean on the first run.

**Lint verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2547_continuing_legal_education_accreditation_credit_reporting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2547_continuing_legal_education_accreditation_credit_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2547_continuing_legal_education_accreditation_credit_reporting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     81
  Calls scanned (§1.8+§1.9):  874

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2547_continuing_legal_education_accreditation_credit_reporting/`):
- `SCAFFOLD.yaml` — 3108 lines. Top-level keys only §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design`).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1669 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4662 lines, single key `scaffold_corner_design`.

**SCAFFOLD.yaml counts:** 14 entities, 9 state machines, 3 concurrency rules, 54 domain constants, 9 calculations, 17 ordered validation rules (priority ladder 10→76), 45 endpoints, 51 error ids, 5 roles. Profile: `compliance_audit` × `ledger_reconciliation`, expert_plus, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / ops_run_checkpoint, flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency.

**§1.8:** 9 difficulty rules / 20 instances.

**§1.9:** 9 sections / 106 instances (81 with full test recipes, 25 `excluded_because:` stubs) — entities 11, state_machines 21, calculations 19, validations 20, endpoints 6, errors 11, rbac 8, cross_cutting_complexity_layers 8, consistency_model 2. All names unique across the §1.8 ∪ §1.9 union; every stub cites a real §1.8 instance; all 51 declared error ids appear in the design files and every `expect_error` names a declared id.

**Design adjudications made:**
- Table 6 (Errors) declares no pattern rows, so errors-section instances carry the Table-4 `violation_to_error` type (documented in a section comment); an invented `error_triggerable` type was removed.
- Table 7 supplies no claim-type column, so rbac uses `role_can_perform_permitted_operations`, `role_cannot_perform_others_exclusive_operations`, the role-model row `segregation_of_duties`, and `peer_roles` for the two `entity_backed` roles (justified in a section comment).
- `ops_run_checkpoint` has no guide row: sweep corners use `scheduled_actions` and the fee ledger uses `derived_field_reconciliation`.
- **SCAFFOLD.yaml amended twice** this pass so the WAIVE corner is airtight: validation priority 20 and `ERR_ROLE_NOT_PERMITTED` now state that a shared endpoint may reserve an action for one role (WAIVE on settlement is BoardAdmin-only).
- `ERR_PROVIDER_NOT_IN_GOOD_STANDING` was re-routed to `POST /cle/courses/{id}/applications` (the sponsor-suspension cascade would otherwise always yield `ERR_COURSE_NOT_APPROVED` first at priority 62).
- Unreachable-by-construction branches documented rather than tested: `late_fee_assessment` step 1, and the comity gate's third `require` (principal office == HOME_JURISDICTION "ST", since "ST" is not a comity jurisdiction).
- `AttendanceReport.days_late` corrected from floor to ceiling in SCAFFOLD.yaml; `Course.expires_at` for LIVE formats is `presented_at + total_minutes`, which forced ON_DEMAND courses in every instance whose clock advances past a sweep.

## Step 3: Copy shared files — 2026-09-03T11:39:29.605Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T12:01:17.205Z

PRD generation complete.

## Output
`workspace/PRD.md` — **518 lines**, ends cleanly on the last row of the §5 error table.

## Section list
- **§1 Introduction**
- **§2 Global Specifications** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim from the fixed contract; verified byte-identical) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Record Identity, Timestamps and Versioning · 2.6 Optimistic Concurrency Control · 2.7 Minutes, Credit Hours and Rounding Discipline · 2.8 Order of Rejection (17 steps) · 2.9 Reference Resolution and Reverse Reachability · 2.10 Cascade Discipline and the Cycle's Two Status Dimensions · 2.11 The Conserved Fee Ledger · 2.12 Denormalized Counters
- **§3 Business Logic & Workflows** (9 subsections) — 3.1 Provider Accreditation Lifecycle · 3.2 Registering a Course · 3.3 Individual Course Approval (info rounds, denial, appeal) · 3.4 Attorney Register and Compliance-Period Derivation · 3.5 Claiming and Verifying Attendance Credit · 3.6 Applying Credit to a Period (caps, chronology, two variants) · 3.7 Out-of-State Instruction: Reciprocity and Comity · 3.8 Certifying a Period, Carryover, Recertification · 3.9 Oversight and Enforcement (complaints, audits, risk scoring, batch run, fees, reinstatement)
- **§4 API Endpoints** — 45-row table
- **§5 Error Codes** — 51-row table

## Coverage (SCAFFOLD §1.1–§1.7)
- **Entities**: all 14 covered; all 161 field/input identifiers appear verbatim in backticks (automated diff: 0 missing), plus all 34 cycle-summary output fields. The three `id`+`created_at`-only entities (CreditAllocation, Affirmation, ReportingSweep) are called out in §2.5.
- **State machines**: all 10 machines and every declared transition, including the parallel `credit_status`/`administrative_status` dimensions, both cyclic loops of CourseApplication, the `SAMPLED → SAMPLED` redraw, and all system-event transitions.
- **Constants**: all 54 present with exact values (numerals normalized to plain digits — 1800, 120000 — so no comma-grouped figure remains).
- **Calculations**: all 9, with pinned orderings spelled out (proration round-then-sum; truncation waterfall GENERAL→BIAS_ELIMINATION→TECHNOLOGY→ETHICS; the seven pinned late-fee steps; risk-score clamp-before-weight with both weighting variants; chronological audit sampling; reciprocity floor-to-15).
- **Validations**: all 17 priorities reproduced in order in §2.8 with their `applies_to` scopes.
- **Endpoints**: all 45, with roles, plus the WAIVE role reservation.
- **Errors**: all 51 in the table, and all 51 also appear in §2/§3 prose next to the rule they guard.
- **Roles**: all 5, with the entity-backed vs opaque identity binding.

## Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS** — 161/161 identifiers + 34 summary fields verified by script.
- **Contract 2 (Rule Coverage): PASS** — transitions, calculations, validations, concurrency rules (3 OCC endpoints), cross-entity cascades, sibling-branch symmetry and the three literal reason strings (`SPONSOR_NOT_IN_GOOD_STANDING`, `COURSE_REVOKED`, `ATTORNEY_ADMIN_SUSPENDED`) all walked.
- **Contract 3 (§3 Path Purity): PASS** — 403 backtick tokens in §3, zero path-prefixed, zero bare methods, zero method+path; zero raw `/cle` occurrences in §3.

Two defects found and fixed during verification: the §4 accreditation-actions row had invented actions (`GRANT_PROVISIONAL`, `LAPSE`) and was corrected to the real six (`GRANT_FULL`, `GRANT_PROBATIONARY`, `DENY`, `RENEW`, `SUSPEND`, `REINSTATE`) with `probation_reason`; and §3.9's lapse paragraph over-generalized the course cascade, now scoped to the `ACCREDITED` branch only. Neither withheld design file was opened.

**Orchestrator truncation check (per pipeline directive):** `tail -25 workspace/PRD.md` ends at `| ERR_INVALID_REQUEST | 422 |` — the final row of the §5 error table, a real section boundary. `grep -n '^#'` confirms all of §1–§5 and all twelve §2 / nine §3 subsections are present. No truncation; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T13:38:00.000Z

Stage 2 complete and audited. Final state:

## Files written

**`test_helpers/` — 9 files, 2,498 lines** (Stage 1): `types.py` 542, `api_client.py` 220, `api_errors.py` 115, `assertions.py` 399, `constants.py` 122, `factories.py` 213, `fixtures.py` 788, `test_users.py` 60, `__init__.py` 39.

**`test_suite/` — 21 files, 12,784 lines**: `conftest.py` 73, then `test_01_register_and_reads` 945, `test_02_sponsor_and_course_lifecycles` 512, `test_03_appeals_audits_and_periods` 977, `test_04_period_requirement_derivation` 380, `test_05_credit_conversion_and_fees` 1306, `test_06_request_and_ordering_checks` 709, `test_07_standing_and_ownership_checks` 798, `test_08_endpoint_contracts` 794, `test_09_uniqueness_and_eligibility` 824, `test_10_role_boundaries` 1141, `test_11_concurrency_and_batch_effects` 634, `test_12_provisional_and_final_credit` 390, `test_13_ceiling_and_rounding_arithmetic` 441, `test_14_review_loops_and_status_dimensions` 296, `test_15_cascade_unwinding` 546, `test_16_check_precedence` 340, `test_17_boundary_instants` 420, `test_18_cross_entity_gating` 372, `test_19_interval_semantics` 485, `test_20_conserved_quantities` 401.

## Coverage — full, with zero instances skipped

- **221 test functions; 235 collected cases** (14 extra from `parametrize` in the role-boundary file). `pytest --collect-only` succeeds with no collection errors.
- **Queue A: 20/20 difficulty instances, 66 tests, every instance >=2** (min 2, max 5).
- **Queue B: 81/81 live corner instances, 155 tests, every instance >=1** (min 1, max 4).
- **The 25 `excluded_because:` entries were not translated**; all 25 cross-references resolve to real difficulty instance names, verified programmatically.

## Audits (all pass, 0 findings)

Every test has exactly one `Design:` line, last in its docstring, resolving to a live instance (no stub tags, no unknown tags, no dual tags). Every docstring citation >=8 words is a verbatim substring of `workspace/PRD.md`. No `skip`/`xfail`/`skipif` anywhere. Zero occurrences of "scaffold", "design index", "Table N" or "§1.x" in generated code. All 30 files parse. No test rewinds the logical clock below the 2026-08-01T00:00:00Z start (28 `set_clock` call sites, all forward).

## Two shared-helper defects found and fixed centrally

1. `CarryoverElection.WAIVE` → **`WAIVE_CARRYOVER`** in `types.py`, and the same value in `assertions.assert_compliance_cycle` — PRD §3.4/§3.8 spell it `WAIVE_CARRYOVER`. (`WAIVE` remains correct for the fee-settlement action.)
2. `AppellantAction.FILE_APPEAL` → **`APPEAL`** in `types.py`, and in `fixtures.setup_appealed_application` — PRD §3.3 and the §4 row both name the action `APPEAL`. No test had used either bad value.

## PRD-defect adjudications (recorded, not worked around silently)

- **Appeal disposition spelling**: §3.3 prose says `GRANT`/`DENY`/`REMAND`; the §4 table says `GRANT_APPEAL`/`DENY_APPEAL`/`REMAND`. Only the request token is ambiguous — the resulting state is uniquely derivable — so `grant_appeal`/`deny_appeal` submit each spelling in turn while every state assertion stays strict. No test hard-codes either spelling.
- **Clock direction**: §2.4 says the board "may move the clock to an arbitrary instant"; the §4 row says "Advances time only; earlier instants are rejected." Treated as advance-only; every design recipe that rewound the clock was shifted forward with all pinned literals preserved, and the one backward-move assertion was dropped as unpinned.
- **§2.8 step 4 foreign-key order**: the governing clause ("in the order the fields appear in the endpoint's input") disagrees with the step's own colon list, so "both FKs unknown" is not derivable; tested as single-unknown probes on which both readings agree.
- **Exact 30-day appeal boundary**: §3.3 "strictly before" vs §2.8 step 10 "no later than" — the exact-instant assertion was dropped; one second either side is tested.
- **One trigger skipped inside a covered instance** (condition b): the *touching* case of concurrent live-session capacity. The PRD never states whether a course's session window is closed or half-open at `expires_at` — pointedly unlike §3.4 (half-open) and §3.9 (closed) — and the outcome flips on that. The instance keeps its collision test and two legal-case tests.
- Several recipes registered courses under an `APPLIED` sponsor, which §3.2 forbids; those chains were rebuilt legally (PROBATIONARY → reviewed course → cleared audit → GRANT_FULL) with all asserted literals unchanged.

Assertion-level drops (instance always kept) were reported per partition and share one cause: values the PRD mentions only inside a formula, absence-of-row checks where no list endpoint is declared, `version` literals that ignore mandated cascade bumps, and orderings of same-instant rows under a frozen clock.

## Step 6: Generate implementation — 2026-09-03T13:38:00.000Z

Implementation complete for task 2547.

## Files written (all under `workspace/implementation/`)

| file | lines |
| --- | --- |
| `start.sh` (executable, guarded `pip install`, `exec python3 app.py`) | 9 |
| `requirements.txt` (`Flask==3.0.3`) | 1 |
| `app.py` | 67 |
| `util.py` (logical clock, ISO-8601 ms format, day/month arithmetic, rounding) | 149 |
| `constants.py` (every pinned domain constant) | 93 |
| `errors.py` (51-entry error catalogue + statuses) | 80 |
| `response.py` (envelope + pagination meta) | 52 |
| `db.py` (in-memory dicts, identity/version discipline) | 132 |
| `middleware.py` (auth, RBAC, shape helpers) | 185 |
| `calc.py` (9 calculations: requirement derivation, proration, credit application, carryover, late fee, risk score, sampling, reciprocity conversion, roster lateness) | 399 |
| `listing.py` | 37 |
| `services/cascades.py` (risk, fee ledger, credit-application persistence, recertification, carryover conservation, provider/course cascades) | 274 |
| `routes/clock.py` / `providers.py` / `courses.py` / `attorneys.py` / `cycles.py` / `credits.py` / `reciprocity.py` / `audits.py` / `complaints.py` / `fees.py` / `sweeps.py` | 18 / 170 / 455 / 202 / 223 / 329 / 211 / 230 / 137 / 74 / 157 |

Total ~3674 lines. **45 endpoints registered**, exactly matching the PRD §4 table (verified via `url_map`). Storage is in-memory dicts only — no SQLite, no disk, no `/tmp`, and no seeding (`grep` for seed/preload/open/sqlite is clean; the store starts empty and `db.reset()` runs at boot).

## Smoke tests (three boots on ports 21547/21548/21549, each killed by PID/port — never a broad `pkill`)

Exercised end-to-end: clock, provider application + `GRANT_FULL` + `PROVIDER_ANNUAL` fee, self-certified and individual-approval course pathways, the full application → info-request → supplement → deny → appeal → grant chain (incl. `ERR_SEGREGATION_OF_DUTIES`), attorney/cycle creation with derived requirements and `filing_deadline` (GROUP_2 → +61 days verified), attendance-code claim (born VERIFIED), affirmation-verified claim with category proration (180-min course, 90 attended → bias 60 / general 30), VOID → earned figures falling, roster filing (1 accepted / 1 skipped, `days_late` 0, `due_at`), reciprocity NY 2 h → 90 min into ETHICS, comity DEFICIENT fork with `comity_claim_id`, complaint substantiation moving the provider to PROBATIONARY, audit open/draw/findings/clear plus `ERR_NO_SAMPLE_POPULATION`, `ERR_AUDIT_PERIOD_OVERLAP`, `ERR_AUDIT_ENGAGEMENT_ACTIVE`, sweep (delinquency + capped 100000 late fee, suspension at 60 days with claim auto-denial + REINSTATEMENT fee, course expiry, provider lapse), fee settlement incl. `WAIVE` reserved to BoardAdmin (403) and `ERR_FEE_ALREADY_SETTLED`, reinstatement gated by `ERR_OUTSTANDING_FEE_BALANCE` then `BOARD_ORDER` → REINSTATED+DEFICIENT, and certification curing a delinquency inside the 7-day grace (LATE_COMPLIANCE → VOIDED, balance back to 0). The 30-field summary payload matches PRD §3.6 field-for-field.

## Ambiguous PRD passages and the interpretation chosen

1. **Appeal dispositions** — §3.3 says `GRANT`/`DENY`/`REMAND`, §4 says `GRANT_APPEAL`/`DENY_APPEAL`/`REMAND`. Both spellings accepted as aliases.
2. **Clock endpoint** — §2.4 allows "an arbitrary instant"; §4 says "Advances time only; earlier instants are rejected". Implemented §2.4/scaffold: never rejects.
3. **Roster on another provider's course** — §2.1 + §2.8 step 5 imply `ERR_NOT_RESOURCE_OWNER`; §3.5 + step 14 name `ERR_COURSE_PROVIDER_MISMATCH`. Used the latter, checked at step 14.
4. **`allegation` length** — scaffold 1..1000 vs PRD 1..2000. PRD wins (2000).
5. **`due_at` on AttendanceReport** — named in §3.5 prose but absent from the scaffold field list; included in the payload.
6. **Attorney standing on reciprocity *determination*** — §3.7 requires ACTIVE/EXEMPT but names no code (step 13 covers only *filing*). Returned `ERR_ATTORNEY_NOT_IN_GOOD_STANDING` (409), checked before the open-cycle precondition, following the prose order of the sentence.
7. **Step-15 inner order for audits** — §2.8 lists overlap before engagement-active; §3.9 prose lists engagement first. Followed §2.8 (normative order-of-rejection).
8. **Substantiating a complaint against a non-revocable course** (PENDING_APPROVAL/DENIED/REVOKED) — the scaffold's Complaint transition carries no course-state precondition, so the complaint still substantiates and the revocation cascade (plus the provider counter bump, which the PRD ties to "the revoked course") is simply skipped rather than raising `ERR_INVALID_STATE_TRANSITION`.
9. **ProviderAdmin ownership on fee settlement** — §2.1's generic provider-ownership sentence enumerates course/audit/roster only, and the scaffold's ownership check likewise omits fee assessments; so only the Attorney branch is ownership-checked. `WAIVE` reservation is enforced at step 2 (before path existence), by peeking at the raw `action`.
10. **Risk refresh on audit open** — "refreshed ... (into `risk_score_at_open`)" read as freezing onto the audit only; the provider row is not touched (no version bump) at open.
11. **`cycles_examined`** counts cycles whose `filing_deadline <= as_of` (scaffold wording); the end-of-sweep risk refresh covers only providers the run actually changed (the lapsed ones).
12. **Version discipline** — a row created inside a request stays at `version` 1 however many times that same request rewrites it (e.g. a roster's `accepted_entry_count` backfill); `db.insert` registers the new id in the per-request touch set.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and could not have read it. Both agents were also explicitly forbidden from reading the other's output directory.

## Step 7: Run tests and iterate — 2026-09-03T13:32:51.000Z

All 8 rounds green. Final report:

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep 1 diagnostic → 6 deterministic failures; sweep 2 confirming → clean), with targeted per-test-isolated re-runs between them to verify each fix.

**Final sweep:** every round `235/235` passed, 0 failed.
- `workspace/implementation/results.1.json` … `results.8.json`.

**Tests deleted:** none. All 6 failures traced to verbatim, uniquely-derivable PRD rules — 4 implementation defects and 2 test-side mistranslations.

**Fixes applied to `implementation/`:**
- `routes/complaints.py` — `_substantiate` / `_bump_substantiated`: the risk refresh ran *before* the `ACCREDITED → PROBATIONARY` cascade, so the provider kept `SELF_CERTIFIED_WEIGHTING`; refresh now happens after the cascade lands, and `probation_reason` records the substantiating complaint (PRD §3.1 "Either way `self_certification_enabled` drops to false, `risk_score_variant` becomes `REVIEWED_WEIGHTING` with the score recomputed under it, and `probation_reason` records the audit or complaint that caused the reversion").
- `routes/audits.py` — `CLOSE_SANCTIONED`/`PROBATION` branch now writes `probation_reason` naming the audit (same PRD sentence).
- `routes/audits.py` — added an explicit `db.touch(audit)` at the end of the audit-action handler: a legitimate `SAMPLED → SAMPLED` redraw that recomputes an identical sample was leaving `version` unbumped, violating PRD §2.5 ("increases by exactly 1 on every mutation") and defeating the §2.6 redraw guard.
- `routes/sweeps.py` — `cycles_examined` now counts every cycle the run iterated, not only those already past `filing_deadline`. PRD §3.9 orders *all* cycles by `filing_deadline` and says the counter "counts the cycles the run considered"; the deadline test lives inside the first enforcement step, and the PRD's own wording that a `SATISFIED` cycle is "skipped" by that step confirms such a cycle was still considered.

**Fixes applied to `test_suite/`:**
- `test_07_standing_and_ownership_checks.py::test_a_suspended_sponsor_blocks_its_own_pending_courses_from_seeking_approval` — the `SUSPEND` setup call submitted a stale `expected_provider_version`; registering the two courses had bumped `courses_total_count` and hence the provider's `version` (PRD §2.10 + §2.12), so the test now reads the sponsor's currently observed version. Test bug, not an OCC defect.
- `test_16_check_precedence.py::test_reinstated_cycle_lets_the_unapproved_course_error_surface_on_the_same_claim` — asserted `administrative_status` on the reinstatement response body, but PRD §4 states reinstatement "is the one exception, returning the reinstated `Attorney` rather than the cycle named in its body"; the assertion now reads the cycle back, keeping the exact `REINSTATED` expectation.

**Fixes applied to `test_helpers/`:** none — no shared fixture, factory or header builder was at fault.

**Notes:** a first-pass grep of `workspace/sweep.log` appeared to show 12 failing tests, but that was interleaving artifact from 8 concurrent rounds writing one log; the `results.$i.json` files showed exactly the same 6 failures in all 8 rounds, i.e. no flakiness and no load-induced failures in either sweep. Storage remains in-memory dicts only (no sqlite/disk/`/tmp`/seeding), verified by grep after the edits.

**Orchestrator independent verification (per memory `prd-bench-step7-verify-sweep-artifacts`):** the orchestrator itself parsed all 8 `workspace/implementation/results.*.json` (mtime 13:21Z, all present and complete JSON) and read `passed`/`total` from each — `235/235` in every one of the 8 rounds. The clean sweep is confirmed against on-disk artifacts, not just the subagent's report. Step 8 is NOT skipped (4 `implementation/` fixes + 2 `test_suite/` fixes).

## Step 8: Finalize PRD — 2026-09-03T13:41:40.000Z

Done. Three surgical edits, all inside §3.9.

## Line counts
- `PRD.md`: 518 lines / `PRD_FINALIZED.md`: 518 lines (paragraph-per-line file). 3 lines revised, 0 added, 0 deleted → **0.58% line delta** (124081 → 125104 bytes, +0.8%).

## Changes
- **§3.9 (Complaints — `SUBSTANTIATE` cascade)** — revise — reordered the provider branch so `substantiated_complaint_count` rises, the provider moves `ACCREDITED → PROBATIONARY`, and *then* `risk_score` is recomputed, stating explicitly that the recompute runs after the status move so the variant reflects post-cascade standing. PRD.md listed the recompute *before* the move, which contradicted §3.1's "`risk_score_variant` becomes `REVIEWED_WEIGHTING` with the score recomputed under it". — `implementation/routes/complaints.py:119-128`
- **§3.9 (Drawing the sample)** — insert — one sentence pinning that every successful audit action bumps the audit's `version` by exactly one even when no field value actually changed (identical redraw). PRD.md left this open: §2.5 bumps on "every mutation", and a no-op redraw is not obviously a mutation. — `implementation/routes/audits.py:237` (`db.touch(audit)`), with `implementation/db.py:96-118` (one bump per row per request)
- **§3.9 (The batch run)** — revise — `cycles_examined` now says it counts every cycle the run walked in that order, regardless of either status dimension and regardless of whether `filing_deadline` has arrived, since the deadline test lives in the first enforcement step. PRD.md's "counts the cycles the run considered" did not decide between all-cycles and past-deadline-only. — `implementation/routes/sweeps.py:68-72`

## Step-7 items that needed **no** PRD edit (already uniquely determined)
- `audits.py` / `complaints.py` writing `probation_reason` — §3.1 already says "`probation_reason` records the audit or complaint that caused the reversion"; the impl's value is free text naming the causing row's id, so no further pinning was added.
- `test_07` stale `expected_provider_version` — §2.12 (`courses_total_count`) + §2.10 ("every row a cascade touches has its `version` incremented, including rows whose only change was a counter") already force the bump. Pure fixture bug.
- `test_16` reinstatement response body — §4 already states reinstatement "is the one exception, returning the reinstated `Attorney`". Pure fixture bug.

## Per-edit pre-edit search log

**Edit 1 — substantiate ordering**
(a) Subject: ordering of `substantiated_complaint_count` bump, `accreditation_status` move and `risk_score` refresh on a substantiated complaint.
(b) Enumerated/read: `routes/complaints.py::_substantiate` (both PROVIDER and COURSE branches) and `_bump_substantiated`; `services/cascades.py::refresh_risk`, `move_provider_status`, `set_fields`; every `refresh_risk`/`move_provider_status` callsite via grep — `routes/audits.py:195,207,223,231,234`, `routes/providers.py:110-168`, `routes/sweeps.py:138-145`, plus the two refresh sites *not* in PRD's "moments" list, `routes/courses.py:188` (self-certified registration) and `routes/credits.py:283` (attendance report).
(c) Adjustment: dropped an "and only then" phrasing that would have made the recompute read as conditional on the move — `_substantiate` calls `refresh_risk` unconditionally in the provider branch, including for a non-`ACCREDITED` provider where no move occurs. Final wording lists the recompute as an unconditional third step whose *position* is after the move. Wording was also kept scoped to the complaint path so it does not narrow §3.9's refresh-moments list (which the impl already exceeds at `courses.py:188` / `credits.py:283`) and does not disturb the course-subject sentence ("never moves its `accreditation_status`").

**Edit 2 — audit action version bump**
(a) Subject: when an audit row's `version` advances.
(b) Enumerated/read: every `provider_audits` reference (grep) — only `routes/audits.py` mutates audit rows: `open_audit` (insert → `version` 1, and `db.insert` pre-registers the row as touched so same-request cascades cannot bump it) and `audit_action` (all four branches + the trailing `db.touch`); `db.py::touch`/`insert`/`_register_touched` for once-per-request semantics; all other explicit `db.touch` sites (`providers.py:169`, `attorneys.py:91,200-201`, `cycles.py:222`, `reciprocity.py:91`) to confirm the "no-op still bumps" guarantee is endpoint-specific rather than global.
(c) Adjustment: scoped the sentence to *audit actions* rather than stating a general "any successful action bumps its target" rule — `cascades.set_fields` bumps only on real change, so a global claim would be false for endpoints without an explicit `touch`. Phrased as "rises by exactly one" to stay consistent with the one-bump-per-request store semantics.

**Edit 3 — `cycles_examined`**
(a) Subject: which cycles the sweep counts as examined.
(b) Enumerated/read: `routes/sweeps.py:58-116` (unconditional `examined += 1` over all of `db.all_rows("compliance_cycles")`, before either enforcement guard), `sweeps.py:44-56` and `:147-157` (the only two writers of `cycles_examined`, confirmed by grep), the sort key at `:59-61`, and `db.IMMUTABLE_COLLECTIONS` (sweep rows carry no `version`, so `set_fields` on the sweep is a plain write).
(c) Adjustment: said "whatever its two status dimensions" instead of enumerating `SATISFIED`/`CLOSED_COMITY`/`REINSTATED`/`ADMIN_SUSPENDED` — the loop filters on nothing at all, so an enumeration risked reading as an exhaustive (and therefore falsifiable) list.

## Step 9: Complete PRD — 2026-09-03T14:11:09.262Z

**Orchestrator decision (recorded per AUTONOMY directive):** Step 9 was executed as **three sequential, file-partitioned passes** over `implementation/` rather than one monolithic scan. Rationale: a single-pass Step 9 on an implementation this large (~3700 lines / 21 modules) has previously no-opped and left `PRD_COMPLETED.md` byte-identical to its source, which silently defeats the step. Partitioning bounds each subagent's read surface and makes the completeness claim auditable per partition. Passes B and C were explicitly forbidden to `cp` over the file so earlier edits survived; each verified a distinctive phrase from every prior pass before exiting.

- **Pass A** — `app.py`, `util.py`, `constants.py`, `errors.py`, `response.py`, `db.py`, `middleware.py`, `listing.py`, `start.sh`, `requirements.txt` → §1, §2.1–§2.10, §5 framing. Seeded `PRD_COMPLETED.md` from `PRD_FINALIZED.md`. **11 edits: 9 ambiguity-pins, 2 mismatch-revisions.** 124,775 → 130,596 chars.
- **Pass B** — `calc.py` (all nine calculations), `services/cascades.py`, `routes/clock.py`, `routes/providers.py`, `routes/courses.py` → §2.4, §2.8, §2.10, §3.1–§3.3, and the arithmetic inside §3.4/§3.6/§3.7/§3.9, plus the §4 clock row. **19 edits: 11 ambiguity-pins, 8 mismatch-revisions.** 130,596 → 134,980 chars.
- **Pass C** — `routes/attorneys.py`, `cycles.py`, `credits.py`, `reciprocity.py`, `audits.py`, `complaints.py`, `fees.py`, `sweeps.py` → §3.4–§3.9 endpoint contracts, guards, error precedence, side effects, response shapes. **22 substantive edits (+4 punctuation repairs to its own inserts): 17 ambiguity-pins, 5 mismatch-revisions.** 134,980 → 139,860 chars.

**Totals: 52 substantive edits — 37 ambiguity-pins, 15 mismatch-revisions.** `PRD_FINALIZED.md` → `PRD_COMPLETED.md`: 518 → 518 lines, 124,775 → 139,860 chars (**+15,085 chars, +12.1%**), 49 lines revised, 0 added, 0 deleted, no new sections.

### Notable mismatch-revisions (PRD prose was wrong about the implementation)
- **§2.2** — `api_request_timestamp` comes from host wall-clock time, not the logical clock; §2.4's "nothing reads the host clock" had admitted the opposite reading.
- **§2.4 + §4 clock row** — the two documents contradicted each other (§2.4 "arbitrary instant" vs §4 "advances only; earlier instants are rejected"). The implementation has **no direction guard**, so both passages were aligned to that: any parsed instant becomes "now". This resolves the self-conflict the Step 5 and Step 6 generators each flagged independently — and resolves it toward the implementation, as Step 9 requires.
- **§2.10** — a cascade stage rewriting a row with values it already holds writes nothing (`updated_at`/`version` untouched).
- **§3.2** — course restoration on renewal fires only on the `LAPSED → PROBATIONARY` branch, not on an `ACCREDITED` self-renewal.
- **§3.3** — `GRANT_APPEAL`/`DENY_APPEAL` declared synonyms of `GRANT`/`DENY`, reconciling §3.3 prose with the §4 table (the second generator-flagged self-conflict, likewise resolved toward the implementation, which accepts both spellings).
- **§3.5** — the claim-requirements list had omitted the sponsoring-provider gate `ERR_PROVIDER_NOT_IN_GOOD_STANDING`.
- **§3.6** — "Live minutes are never capped" was over-broad: no *format* cap keys on `LIVE`, but the `source`-keyed reciprocity allowance still narrows reciprocity records, which are always `LIVE`.
- **§3.7** — the comity determination *persists* the final-variant run into the cycle's five `earned_*` fields and every record's `countable_minutes` while the cycle is still `OPEN`.
- **§3.9** — the risk-refresh moment list was falsely exhaustive (missing self-certified course registration, roster acceptance, `ISSUE_FINDINGS`); and the batch run's end-of-sweep refresh covers exactly the providers that run drove into `LAPSED`, not "every provider the run touched".
- **§3.9** — fee `PAY` is open to board, `ProviderAdmin` and the named attorney, with ownership binding the `Attorney` role alone.

### Deliberately left unpinned (aggregated across passes, with reasons)
- All 60+ `constants.py` values and the entire `errors.py` → §5 status mapping were verified **byte-identical to the PRD** — zero mismatches, so no edits.
- Unreachable-by-construction defensive branches (unknown `compliance_group` → 0-day offset, `total_minutes <= 0` proration, `effective_format` fallthrough, zero-denominator delinquency, `ApiError`'s 400 fallback, review `DENY` on a course already out of `PENDING_APPROVAL`): pinning them would document behavior the API cannot exhibit.
- `app.py`'s catch-all `Exception` → 422 handler: an internal safety net, not intended behavior; documenting it would invite tests against crash paths.
- `start.sh` / `requirements.txt` runtime detail (Flask 3.0.3, `PORT` default 10000, `0.0.0.0`, `threaded=False`): deployment concern, not API contract. (`threaded=False` is what makes the `flask.g`-based once-per-request version set safe — mechanism, not wire behavior.)
- Literal `probation_reason` strings (`"Audit sanction <id>"` etc.): §3.1 already pins that the field records the causing audit or complaint; the format is an impl detail.
- Unobservable guard orderings (reinstatement's two `ERR_INVALID_STATE_TRANSITION` guards; `_session_conflict` probing only window-start instants, which is mathematically equivalent to maximum overlap depth).
- §2.8 step 5 lists "reinstatement" among ownership-checked operations though `attorneys.py` applies no ownership test — the listing is vacuous rather than wrong (the endpoint admits `BoardAdmin` only, so no entity-backed role can reach the step), and pass C stated the absence explicitly in §3.9 instead.

### Orchestrator final verification (on-disk, not subagent-reported)
- `cmp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` → **differs** (the byte-identical no-op failure mode did NOT occur).
- `diff` of all `^#` lines between the two files is **empty** — heading structure preserved, no sections added or dropped; §4 still 45 data rows, §5 still 51.
- `tail` ends on `| ERR_INVALID_REQUEST | 422 |`, the final row of the §5 table — a real section boundary, not mid-sentence.
- `find workspace/implementation -name '*.py' -newer results.1.json` → **empty**: no implementation file was modified after the green Step 7 sweep, so the eight `results.*.json` at 235/235 remain valid evidence for the artifact as shipped.

## Pipeline complete — 2026-09-03T14:11:09.262Z

All nine steps executed. Final artifact set present in the task directory: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (21 files, 235 collected cases), and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (45 endpoints) and `results.1.json`–`results.8.json` all at 235/235.
