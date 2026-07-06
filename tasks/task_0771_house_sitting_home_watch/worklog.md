# Worklog — task_0771_house_sitting_home_watch

## Step 1: Create task directory — 2026-07-06T03:00:00.000Z

Created `tasks/task_0771_house_sitting_home_watch/` and `tasks/task_0771_house_sitting_home_watch/workspace/`. Scenario: House-Sitting & Home-Watch Service (Expert difficulty).

## Step 2: Generate scaffold — 2026-07-06T03:25:00.000Z

All three files written; scaffold lint passes clean.

**Archetype:** workflow_orchestration + temporal_windowing, flat topology, peer_roles (Client/Sitter entity-backed, Coordinator opaque), immediate consistency. Difficulty band: Expert.

- **11 entities:** Client, Property, Sitter, BackgroundCheck, CoveragePolicy (insurance/bond), Booking (recurring vs vacation), Visit, VisitLogEntry (append-only photo/GPS, common_fields:false), KeyAssignment, Incident, Invoice.
- **6 state machines:** BackgroundCheck (branch), Booking (SCHEDULED↔PENDING_ASSIGNMENT assign/unassign cycle), Visit (IN_PROGRESS→FLAGGED branch-fork), KeyAssignment, Incident (escalate/resolve branch), Invoice.
- **5 calculations:** recurrence_visit_generation, per_visit_charge (tiered + provisional/final dual-variant), invoice_financials (pinned discount↔fee↔total order), incident_liability_exposure (estimated/settled dual-variant), sitter_reliability_score.
- **1 concurrency rule:** OCC on Sitter.version for coverage-policy supersede (412).
- **19 ordered validations, 48 endpoints** (incl. /_clock/set_current_utc, default 2026-03-01T00:00:00Z), **45 errors, 3 roles**.
- **§1.8:** 9 difficulty rules × 2 = 18 instances. **§1.9:** 21 active + 3 excluded_because stubs.
- Lint VERDICT: clean (440 calls checked).

## Step 3: Copy shared files — 2026-07-06T03:26:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-06T03:32:00.000Z

Generated `workspace/PRD.md` (293 lines) from SCAFFOLD.yaml (Expert, /home-watch prefix). All three Hard Contracts pass (field coverage 67/67; rule coverage 0 missing; path purity 0 violations).

Notable faithfulness calls:
- Ordered validation conflicts rendered explicitly (assign: cleared→bond→reliability→schedule; check-out: evidence→checklist).
- Sibling-branch symmetry for incident resolution (OPEN→RESOLVED vs ESCALATED→RESOLVED) written with equal density.
- Buffered-overlap rule: scaffold references BUFFER in schedule-conflict condition but defines no numeric constant → two-sided inequality described in prose without inventing a value (possible unique-derivability gap for that difficulty instance).
- All calculation formulas translated to precise prose (pinned discount→fee→tax order; clamped duration factor provisional 1.0 vs final).

## Step 5: Generate unit tests — 2026-07-06T03:49:00.000Z

test_helpers/ (9 files) + test_suite/ (conftest + 9 files, 57 test functions).
- Queue A (Difficulty): all 18 instances × 2 tests = 36, tagged Design: Difficulty/<rule_id>/<name>.
- Queue B (Corner): all 21 non-stub instances × 1 test = 21, tagged Design: Corner/<section>/<name>.
- 3 excluded_because stubs correctly not translated (resolve to owning difficulty instances).
- No instances skipped; all 39 non-stub instances passed the PRD-first two-condition filter. Both priority_pair_validation_conflict instances survived (PRD explicitly pins order).
- Billing constants validated: provisional 6500 / final 9750, weekend 10625, invoice subtotal 16250 → fee 1300 → tax 1229 → total 18779.

## Step 6: Generate implementation — 2026-07-06T03:49:00.000Z

workspace/implementation/: app.py (~1050 lines), start.sh (guarded deps, exec python3 app.py, reads $PORT, binds 0.0.0.0), requirements.txt (flask==3.0.3). 45 endpoints. In-memory only, no seeding.
- Logical clock default 2026-03-01T00:00:00Z; Decimal ROUND_HALF_UP money.
- Sitter.version bumps only on coverage-policy issue (sole OCC path per PRD 2.6); other side-effects touch updated_at without version bump.
- Validation precedence wired per PRD 2.8 + endpoint orderings.
- Schedule-conflict buffer set to 0 (scaffold defines no BUFFER constant).
- Self-validation end-to-end scripts passed (happy path + error/edge cases).

## Step 7: Run tests and iterate — 2026-07-06T04:00:00.000Z

All 8 parallel rounds pass 57/57. Clean sweep.

**Iterations run:** 2 (baseline sweep + 1 fix, then confirming sweep).
**Tests deleted:** None.
**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/ (app.py):**
Replaced `touch_no_version(sitter)` with `touch(sitter)` at all 6 sitter-mutation sites. Root cause: PRD §2.4 states verbatim "on every mutation that changes the resource, `updated_at` is refreshed... and `version` is incremented by one." Impl was suppressing the version bump on sitter mutations. Fix increments version on every genuine sitter mutation:
- submit_bgcheck (directly-tested case; PRD §3.2)
- decide_bgcheck CLEARED branch (+ possible ONBOARDING→ACTIVE promotion)
- decide_bgcheck REJECTED branch
- missed-visit handler (missed_visit_count + reliability recompute)
- incident-escalation handler (escalated_incident_count + reliability recompute)
- incident-settlement handler (ACTIVE→SUSPENDED on policy exhaustion)
`touch()` guards versionless entities; coverage-policy fixtures read the sitter's live version dynamically, so no fixture broke.
**Result:** 8/8 parallel rounds pass 57/57.

## Step 8: Finalize PRD — 2026-07-06T04:05:00.000Z

No edits made. `PRD_FINALIZED.md` is byte-identical to `PRD.md` (293 lines, 0% delta). The single Step 7 fix (touch_no_version→touch on sitter) was a pure implementation bug fixed *toward* PRD §2.4's already-explicit universal rule ("on every mutation... version is incremented by one"). Not a PRD silence, not a mismatch. Pre-edit search confirmed all 6 sitter-mutation sites are genuine mutations covered by §2.4 (with §2.6 additionally pinning coverage-policy issuance). No PRD change required.

## Step 9: Complete PRD — 2026-07-06T04:10:00.000Z

Produced `PRD_COMPLETED.md` from PRD_FINALIZED.md. 293 lines, char delta +874 (all in-paragraph). Ambiguity-pins: 5. Mismatch-revisions: 0.

- §2.3 Pagination — insert — pinned out-of-range limit/offset clamped (not rejected), unparseable falls back to defaults, created_at ties break by ascending creation sequence (app.py:352-385).
- §3.4 Assignment (Schedule qualification) — insert — pinned unstated buffer magnitude to zero → strict overlap of the two 30-min windows (app.py:38, 937-942).
- §3.7 Incidents (filing) — insert — pinned filing requires visit IN_PROGRESS, else ERR_VISIT_NOT_IN_PROGRESS; at most one incident per visit (app.py:1344-1345).
- §3.7 Incidents (flagged check-out) — revise — pinned ERR_UNRESOLVED_INCIDENT evaluated first, ahead of evidence/checklist (app.py:1144-1153).
- §3.7 Incidents (resolve payout) — insert — pinned that with no applicable liability policy, settled payout equals assessed damage uncapped (app.py:1400-1409).

Non-changes verified already-pinned: financial roll-up order/rates/rounding, all validation-precedence orderings, error-code/HTTP-status catalogue, key conservation, reliability formula/suspension, cancellation cascade.

---

**PIPELINE COMPLETE.** All 9 steps done. Final state: 57 tests, 8/8 parallel rounds pass 57/57. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (+5 ambiguity pins), test_helpers/ + test_suite/ (57 tests), workspace/implementation/ (Flask, 45 endpoints, in-memory).
