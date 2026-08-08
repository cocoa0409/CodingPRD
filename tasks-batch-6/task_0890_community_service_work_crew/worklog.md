# Worklog — task_0890_community_service_work_crew

## Step 1: Create task directory — 2026-07-29T11:00:00.000Z

Output folder pre-created per orchestrator args; Step 1 scan skipped. Created workspace/ subdir.

## Step 2: Generate scaffold — 2026-07-29T11:20:00.000Z

Generated a fresh **Expert**-difficulty scaffold for the Community-Service & Work-Crew Program, built purely from the scenario and the scaffold-generator spec (no sibling tasks consulted).

**All three files written and verified:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Scaffold metrics:**
- **Entities: 10** — Participant, Site, InsurancePolicy, Supervisor, Referral, Placement, WorkSession, FeeConversion, ComplianceAction, Certificate (flat topology, 10 FKs all with reverse-reachability GETs)
- **State machines: 6** — Site, InsurancePolicy, Referral (cyclic ACTIVE↔NON_COMPLIANT), Placement (cyclic suspend/reinstate), WorkSession (parallel attendance × verification axes), FeeConversion (branching)
- **Endpoints: 48** (incl. `/_clock/set_current_utc` with default `2026-05-01T00:00:00Z`)
- **Calculations: 7** — including dual-variant claimed-vs-verified hours, provisional-vs-final conversion fee, tiered/clamped fee (mode a), round-per-session-then-sum (mode b), hours-partition and money-ledger conservation
- **Errors: 21**; **Roles: 4** (CourtClerk/ProgramCoordinator opaque; SiteSupervisor/Participant entity-backed; four-eyes SoD on fee approval)
- **Concurrency: 1** OCC rule (stale referral version on fee-conversion create, CREATE-supersede)

**Design coverage:** all nine §0.5 Difficulty Rules satisfied with 2 instances each (18 §1.8 instances); 30 active §1.9 corner instances + 5 excluded stubs. All 53 instance names unique.

**Validation:** all three files parse under `yaml.safe_load` (fixed one nested-`[` flow-sequence issue in corner `grounds:` by quoting elements); `scaffold_lint.py` returns `VERDICT: clean lint` (412 calls scanned); no forbidden concurrency vocabulary present.

## Step 3: Copy INSTRUCTION.md — 2026-07-29T11:20:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-29T11:25:00.000Z

PRD written to workspace/PRD.md. Line count: 272. Endpoints documented: 48 (§4 table). Entities: 10. Errors: 21.

Hard-contract verification all PASS (field-name coverage, rule coverage, §3 path purity 0 violations). Domain characteristics captured: dual-variant calculations (self-reported vs supervisor-attested hours; provisional quote vs final settlement fee), conserved hours partition (ordered = completed + converted + outstanding), four-eyes SoD on fee-conversion approval, OCC on referral version, cascading suspension/termination/completion, two independent WorkSession axes, immutable common_fields=false records (ComplianceAction, Certificate carry only id/created_at).

## Step 4.5: Pre-Step-5 undeclared-constants check — 2026-08-01T00:00:00.000Z

RESUME pass (weekly-rate-limit kill at Step 4→5 boundary). On-disk verified: SCAFFOLD.yaml (+2 design files), workspace/INSTRUCTION.md, workspace/PRD.md all present; no test_suite/test_helpers/implementation/results yet. All 3 scaffold files parse under yaml.safe_load.

Scanned SCAFFOLD.yaml for undeclared constants (named thresholds/windows with no value). ALL named constants are declared with values and are reflected concretely in workspace/PRD.md — nothing test-determinative left dangling:
- QUARTER_HOUR = 0.25 (grid; PRD §3 "quarter-hour grid")
- BASE_CONVERSION_RATE_CENTS = 1500; INDIGENCY_MULTIPLIER = {NONE:1.0, PARTIAL:0.5, FULL:0.25}; MIN_FEE_CENTS = 2500; MAX_FEE_CENTS = 200000 (PRD §3.6 line 173: "base of 1500 cents ... 1.0/0.5/0.25 ... floor of 2500 ... ceiling of 200000")
- REST_BUFFER_MINUTES = 60 (PRD §3.4 line 145: "under 60 minutes ... exactly 60 allowed; 59 rejected")

No SCAFFOLD/PRD patch needed. Proceeding to Steps 5 & 6.

## Step 7: Test-and-fix loop — 2026-08-01T00:00:00.000Z

All 8 rounds pass 66/66 with zero skip/xfail. Clean sweep achieved. NOT clean-first-sweep (2 iterations: baseline + 1 fix batch). Orchestrator independently re-parsed all 8 results.N.json: passed==total==66, failed==0, skipped==0 in every round; grep skip/xfail matched only the "skipped": 0 summary field.

Iterations run: 2 (baseline + 1 fix batch).
Initial state: 64/66, 2 tests failing identically across all 8 rounds (deterministic, not flaky).
Tests deleted: None. Both failures traced to real bugs (one impl, one fixture).

Fixes applied to test_helpers/:
- test_helpers/fixtures.py — two_placements_same_site: added same_supervisor=True param. When False, each placement gets its own supervisor at the same site (also exposes supervisor2_id). Why: test_site_capacity_exceeded_across_participants needs two overlapping sessions on one capacity-1 site under DISTINCT supervisors; the fixture previously reused one supervisor so the supervisor double-booking guard (PRD §3.4, evaluated before site capacity) tripped first → ERR_SUPERVISOR_DOUBLE_BOOKED instead of the asserted ERR_SITE_CAPACITY_EXCEEDED. The double-booking test still uses the default (shared supervisor).
- test_suite/test_04_scheduling_guards.py — test_site_capacity_exceeded_across_participants now calls the fixture with same_supervisor=False.

Fixes applied to implementation/:
- workspace/implementation/app.py — session_create (POST /work-sessions): removed the guard `if placement.status != ACTIVE: raise ERR_INVALID_STATE`. Why: PRD §3.4 enumerates exactly three scheduling guards (rest buffer, supervisor double-booking, site capacity); "scheduled under an active placement" is descriptive prose, not a stated guard with an error. This unstated guard made the verbatim check-in guard ERR_PLACEMENT_NOT_ACTIVE (PRD §3.5, line 153) unreachable — the only PRD path to a SCHEDULED session on a non-ACTIVE placement is scheduling on a PROPOSED placement (suspension cascades cancel SCHEDULED sessions). This unblocked test_checkin_on_proposed_placement_rejected. Confirmed no test asserts scheduling-rejection on a non-active placement, so removal is safe.

Final confirmation: all 8 results.N.json show passed==total==66, 0 failed/errors/skipped.

## Step 8: Finalize PRD — 2026-08-01T00:00:00.000Z

Step 7 was NOT clean (1 impl fix + 1 fixture fix) → Step 8 ran. PRD_FINALIZED.md produced with one edit.

Line counts: PRD.md 272, PRD_FINALIZED.md 272. One line revised in place; 0% line-count delta (single-line content change within §3.4).

Changes (1):
- §3.4 (Scheduling Work Sessions) — revise — Removed the claim that a session is "scheduled under an active placement" and added that scheduling does not check the placement's status (a session may be scheduled under a placement in any status, e.g. a PROPOSED one), with only the three listed guards applying — matches implementation/app.py session_create (no placement-status guard).

Pre-edit search log: subject = whether scheduling validates placement status. Enumerated session_create (only guards: rest buffer/supervisor double-book/site capacity, no placement-status check); cross-checked session_check_in (ERR_PLACEMENT_NOT_ACTIVE remains reachable at check-in only, §3.5 untouched) and cancel_scheduled_sessions (SCHEDULED cancelled on suspend/terminate). Wording chosen non-narrowing ("does not check the placement's status ... in any status", PROPOSED as non-exclusive example).

Not patched (fixture-only, no PRD silence): the same_supervisor test-scaffolding fix exposes guard ordering (supervisor double-booking before site capacity) already uniquely determined by PRD §3.4 ordering; no PRD edit warranted.

## Step 9: Complete PRD — 2026-08-01T00:00:00.000Z

Full PRD-vs-implementation completeness scan produced workspace/PRD_COMPLETED.md.

Source vs completed: PRD_FINALIZED.md 272 lines / 37,996 chars → PRD_COMPLETED.md 272 lines / 40,291 chars (+2,295 chars, 0 net lines). All edits in-paragraph (no new lines/sections). Verified: PRD_COMPLETED.md present, larger than source, same 5 top-level ## sections, differs from PRD_FINALIZED (not a byte-identical copy), ends with the error-catalogue table.

Counts: 8 ambiguity-pins, 1 mismatch-revision (9 edits total).

Changes:
- §2.4 — insert — ambiguity — "current clock" fields (waiver_signed_at, defaulted check_in_at/check_out_at, issued_at) and input date fields store raw clock/input string verbatim (not re-rendered to canonical 3-digit), while api_request_timestamp is logical clock in canonical 3-digit — app.py CLOCK_RAW vs _canonical3.
- §2.7 — revise — mismatch — fees_settled_cents is sum over PAID conversions only; a reversed conversion drops out (not additionally subtracted), full reversal nets to zero not negative. PRD previously said "PAID minus REVERSED" — app.py recompute_ledger.
- §2.3 — insert — ambiguity — created_at tie-break by insertion sequence + optional exact-match list filter query params.
- §3.5 — insert — ambiguity — void not placement-ownership-gated (any SiteSupervisor), unlike check-in/out/verify.
- §3.5 — revise — ambiguity — void-reopen: referral → ACTIVE + certificate_id cleared, cascaded-COMPLETED placements left COMPLETED; ERR_INVALID_STATE terminal guard applies only to VERIFIED sessions.
- §3.6 — insert — ambiguity — approved_by_user_id, settled_hours, settlement_fee_cents null on creation until later steps populate them.
- §3.6 — revise — ambiguity — reverse-of-CONVERTED: restores ACTIVE + clears certificate_id, placements left COMPLETED.
- §3.7 — insert — ambiguity — REPORT_BACK against non-ACTIVE referral → ERR_INVALID_STATE; WARNING has no state guard and records current status.
- §3.8 — insert — ambiguity — certificate_number format CERT- + zero-padded six-digit sequence.

## Pipeline complete — 2026-08-01T00:00:00.000Z

RESUME pass (Steps 5–9 after weekly-rate-limit kill at Step 4→5 boundary). Task GREEN: 66/66 × 8 rounds durable (results.1.json..results.8.json), 0 skip/xfail. Steps 1–4 verified on-disk (not regenerated). NOT clean-first-sweep: 1 impl fix (removed unstated placement-ACTIVE scheduling guard) + 1 fixture fix (same_supervisor param) → Step 8 ran (1 §3.4 edit) → Step 9 (8 pins + 1 mismatch-revision). No undeclared constants required pinning.
