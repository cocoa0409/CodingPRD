# Worklog — task_0760_volunteer_fire_ems

## Step 1: Create Task Directory — 2026-07-05

Pre-assigned folder `tasks/task_0760_volunteer_fire_ems` used as-is (Step 1 directory scan skipped per instructions). Created `workspace/` subdirectory. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-05

Three artifacts written to task_dir and lint-clean (scaffold_lint.py: VERDICT clean lint — 75 endpoints, 14 entities, 18 §1.8 + 29 §1.9 instances, 371 calls scanned).

### Design overview
- **Archetype**: posture-driven gating + compliance/audit; **flat** topology (empty `api_prefix`, peer top-level collections); **parallel** state-machine shape; `hierarchical_override` roles; immediate consistency.
- **Entities (14)**: Member, Certification, TrainingRecord, PointAdjustment, Station, Apparatus, Equipment, MaintenanceWindow, DutyShift, DutyAssignment, Incident, TurnoutResponse, FundraisingCampaign, Donation.
- **State machines (10)**: Certification (cyclic CURRENT→EXPIRING→EXPIRED→CURRENT), Incident (parallel response_status × report_status dims), Member (ACTIVE↔LOA cycle), Equipment, MaintenanceWindow, DutyShift, DutyAssignment, TurnoutResponse, Campaign, Donation.
- **Calculations (10)**: dual-variant `cert_completed_hours` (STRICT vs CARRYOVER) and `member_stipend` (PROVISIONAL vs FINAL); combinatorial `turnout_points` (mode a) and pinned tier→waiver order in `member_stipend` (mode c); conserved `member_points_ytd` (points) and `campaign_raised` (money); derived `apparatus_posture`, `shift_staffing`, `stipend_tier`, `response_eligibility`, `duty_points`.
- **Concurrency (2 OCC)**: `duty-assignment-create-stale-shift` (DutyShift.version), `report-amend-stale-incident` (Incident.version) — both 412, expected-version required + version bump.
- **Endpoints**: 75 (incl. `/_clock/set_current_utc` default `2026-03-01T00:00:00Z`, `certifications/sweep`, `duty-shifts/sweep`; every FK has reverse-reachability GET).
- **Errors**: 26. **Validations**: 11 priorities (auth → validation → existence → state → safety → referential → temporal → constraint → fiscal → OCC).
- **Roles (3)**: Chief (opaque), Officer (entity_backed:Member), Member (entity_backed:Member).
- All 9 difficulty rules covered (2 instances each). No sibling task directories read.

## Step 3: Copy Shared Files — 2026-07-05

`cp ./INSTRUCTION.md workspace/INSTRUCTION.md` — copied (1424 bytes).

## Step 4: Generate PRD — 2026-07-05

Output `workspace/PRD.md` — 322 lines, 5 top-level sections, 17 subsections. All 3 hard contracts PASS: Field-Name Coverage (0 missing), Rule Coverage (both OCC rules, all state transitions, both cascades, all 9 calculations, validation precedence, all constants embedded), §3 Path Purity (0 path tokens / bare methods). Withheld design files not opened.

## Step 5: Generate Unit Tests — 2026-07-05

`test_helpers/` (9 files) + `test_suite/` (conftest + 7 test files, 63 tests). Queue A (Difficulty): all 18 instances × 2 tests = 36. Queue B (Corner): all 26 non-stub instances covered (27 tests). 3 `excluded_because:` stubs not translated. No instances skipped — PRD covers every asserted rule verbatim and uniquely. 63 tests collect without error; every `Design:` tag maps to a real instance; ~65 PRD citations spot-checked verbatim; no scaffold leakage, no skip/xfail markers.

Design notes: two recipes capture a shift's version at create then reuse after publish; since PRD §2.4/§3.4 make publish increment version, OCC/assignment calls use current version (PRD-faithful) preserving stale/current relationship + asserted error_id (literal version ints never asserted). Officer ops on other members' resources follow non-ownership reading (only PRD ownership check is Member check-in, tested directly).

## Step 6: Generate Implementation — 2026-07-05

Python + Flask in-memory impl at `workspace/implementation/` (3 files: start.sh, requirements.txt flask==3.0.3, app.py ~1200 lines). 70 routes. start.sh: guarded-install, reads $PORT (default 10000), binds 0.0.0.0, exec foreground.

Key decisions: all derived fields computed live (never stored) → conserved-quantity invariants hold automatically; storage strictly in-memory module dicts, nothing seeded, clock defaults 2026-03-01T00:00:00Z; version bumps on stored-field mutations (assignment-create bumps parent DutyShift.version for OCC 412; incident lock/amend bump Incident.version); validation precedence per §2.6 (report amend: NFIRS-completeness band 9 before OCC band 11); Decimal ROUND_HALF_UP for money/points; integer ceil for scene hours. Interpretation: cancel-future-assignments cascade on LOA AND retire/expel per §3.4. Smoke-tested end-to-end (auth, cert gate, OCC, turnout points+conservation, Cascade-2, duty sweep, NFIRS lock/amend, rest-buffer, dues gate, GOLD stipend) — all correct.

## Step 7: Run Tests and Iterate — 2026-07-05

**Iterations run:** 2 (initial diagnosis + fix, then a clean re-sweep to clear host-saturation noise). Final: 63/63 passing in all 8 rounds.

**Tests deleted:** None. All 63 tests are PRD-faithful.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- `workspace/implementation/app.py`, `sweep_shifts()` (the `/duty-shifts/sweep` handler): the PUBLISHED→IN_PROGRESS transition was gated on `s["start_at"] <= clock < s["end_at"]`. When the sweep is first run *after* `end_at` (which `create_verified_duty` does — checks a member in, then runs a single sweep past `end_at`), a still-PUBLISHED shift never entered IN_PROGRESS, so the second loop never completed it and the roster never settled. Assignments stayed `CHECKED_IN` instead of `VERIFIED`, and verified duty points were never credited. Changed the guard to `s["start_at"] <= clock`, so a shift whose start has arrived becomes IN_PROGRESS and — if its `end_at` has also passed — is completed by the second loop in the same sweep. Faithful to PRD §3.5. Resolved both original failures: `test_duty_points_for_12h_shift` (assignment now reaches VERIFIED) and `test_stipend_final_basis_excludes_scheduled_duty` (FINAL-basis points_ytd now 15 = 9 turnout + 6 verified duty).

**Note:** Intermediate rounds showed a few "API server could not be restarted" setup errors — documented single-task host-saturation boot-timeout artifacts (hit different tests each round; some rounds fully clean). A re-run produced 63/63 in all 8 rounds with zero errors, confirming spurious.

## Step 8: Finalize PRD — 2026-07-05

Output `workspace/PRD_FINALIZED.md`. PRD.md 322 lines → PRD_FINALIZED.md 322 lines (1 line revised at line 173, 0% line delta, in-place edit).

**Change:** §3.4 (Duty Shifts / shift sweep, line 173) — revise — removed PRD's `end_at`-not-yet-passed gate on the `PUBLISHED → IN_PROGRESS` sweep transition and stated both hops run in one sweep, so a still-PUBLISHED shift whose start and end have both passed reaches `COMPLETED` in a single sweep — `implementation/app.py:1436` (+ completion loop `:1442`).

Pre-edit search: grepped `IN_PROGRESS|PUBLISHED|start_at|end_at|sweep` across app.py; confirmed only shift IN_PROGRESS/COMPLETED writes are in `sweep_shifts()` (:1428–1457); other IN_PROGRESS sites (:496/1262/1304/1315) are MaintenanceWindow not shifts; cross-checked §3.4:179 and §3.3:165 Cascade 2 — no conflict. No other <step_7_diff> items (no deletions, no test_helpers fixes).

## Step 9: Complete PRD — 2026-07-05

Output `workspace/PRD_COMPLETED.md`. PRD_FINALIZED.md 322 lines / 48,374 chars → PRD_COMPLETED.md 322 lines / 49,371 chars (+997 chars, line count unchanged — all in-paragraph). Counts: ambiguity-pins 3, mismatch-revisions 1.

**Changes:**
- §2.2 (API Response Structure) — revise — mismatch — PRD said 2xx-no-data returns "empty object"; impl returns JSON `null`. Pinned sole no-payload case (clock-set) returns `data: null` — app.py:763 / envelope :161.
- §2.3 (Pagination) — insert — ambiguity — out-of-range `limit` clamped, non-integer `limit`/`offset` fall back to defaults, negative `offset` floors to 0; list ties on identical `created_at` broken by ascending creation sequence — app.py:178-199, :363-364.
- §3.2 (Certifications) — insert — ambiguity — cert-sweep returns `data` array of exactly the transitioned certifications (unchanged omitted), ordered created_at asc, ties by creation sequence — app.py:1030-1031.
- §3.4 (Duty Scheduling) — insert — ambiguity — shift-sweep returns `data` array of exactly the transitioned shifts (each once across two-hop advance), created_at asc, ties by creation sequence, unchanged omitted — app.py:1454-1457.

Verified already-pinned (no change): §2.6 validation bands, turnout/duty formulas + half-up rounding, stipend/dues-waiver order, posture + Cascades 1&2, cert cycle/carryover (8h cap, 90-day pre-window), NFIRS lock/amend revision+version increments (completeness-before-OCC), conserved ledgers, all serializer shapes.

---

## Pipeline complete — 2026-07-05

All 9 steps done. Final state: 63/63 tests passing across all 8 stability-sweep rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files) + test_suite/ (7 files, 63 tests), workspace/implementation/ (app.py + start.sh + requirements.txt).
