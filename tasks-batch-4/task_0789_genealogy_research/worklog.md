# Worklog — task_0789_genealogy_research

## Step 1: Create task directory — 2026-07-07T10:59:32.000Z

Pre-assigned folder tasks/task_0789_genealogy_research verified (workspace/ subdirectory present). Skipped Step 1 index scan per run instructions. Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-07T11:26:05.000Z

All literals verify and the package is lint-clean. The scaffold for task_0789_genealogy_research is complete.

### Summary

Generated three lint-clean files:
- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency rules; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**`scaffold_lint.py` verdict: clean lint** — all 262 §1.8/§1.9 calls conform to §1.5, and all §1.1 FKs have reverse-reachability GETs.

Counts (Expert band):
- Entities: 14 (Client, Researcher, Repository, ResearchProject, RecordSearch, SourceCitation, Person [self-referential family tree via father_id/mother_id], DnaInterpretation, DocumentRequest [parallel retrieval×translation dims], HeirloomItem, Deliverable, Milestone, TimeEntry, RepositoryAppointment)
- Endpoints: 60 (flat topology, one clock test-driving endpoint `/genealogy/_clock/set_current_utc`)
- State machines: 11 (Person cyclic reopen, DocumentRequest parallel dimensions, Deliverable revision cycle, Milestone billing, plus linear pipelines)
- Calculations: 5 (project_cost dual-variant, person_confidence dual-variant, milestone_invoice_amount, project_billable_amount per-milestone-rounding, dna_predicted_relationship threshold)
- Validations: 16 ordered rules; Errors: 30
- §1.8 depth rules: 9 rules × 2 = 18 instances
- §1.9 corner instances: 21 active + 3 excluded_because stubs (24 total) across all 9 taxonomy sections

Notable Expert mechanics: depth-4 citation→person-confidence→person-verify→project-research-complete cascade; two temporal-overlap semantics (buffered-exclusive on Researcher vs aggregate-capacity on Repository); two conservation invariants (consumed_hours on time-entry void; net-billed money on milestone cancel); nested-rounding trap where per-milestone agency-fee rounding (26532) diverges from sum-then-round (26531). All formula-derived asserts are pre-computed literals; OCC reconfigure uses `${var}` version references.

Verified: all three files exist and `yaml.safe_load` cleanly.

## Step 3: Copy INSTRUCTION.md — 2026-07-07T11:26:05.000Z

Copied ./INSTRUCTION.md → tasks/task_0789_genealogy_research/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-07T11:32:24.000Z

Generated workspace/PRD.md (269 lines) from the genealogy-research scaffold.

Metrics:
- Endpoints documented: 60 of 60 (verified programmatically, 0 missing; parity with SCAFFOLD.yaml confirmed by orchestrator: 60 == 60)
- Errors: all 30 error codes present in §5 catalogue

Hard Contract results (all PASS):
- Contract 1 (Field-Name Coverage): 92 required identifiers, 92 present, 0 missing.
- Contract 2 (Rule Coverage): all five calculations rendered as precise prose with pinned rounding order; state machines, cascades, OCC reconfigure rule, and validation priority orderings all in prose.
- Contract 3 (§3 Path Purity): 390 backtick tokens in §3; 0 URL-path/bare-method/method+path tokens.

Both withheld design files were not read or referenced.

## Step 5: Generate unit tests — 2026-07-07T11:47:58.000Z

Stage 1 — test_helpers/ (9 files): types.py, api_client.py (~60 methods), api_errors.py (31 errors), assertions.py (incl. assert_project_ledger_invariants), factories.py, constants.py, test_users.py (opaque ProjectManager + per-instance client/researcher header builders), fixtures.py (5 tiers), __init__.py.

Stage 2 — test_suite/ (6 domain test files + conftest, 57 tests):
- Queue A (Difficulty): 36 tests — every one of the 18 difficulty instances has exactly 2 tests.
- Queue B (Corner): 21 tests — every one of the 21 non-stub corner instances has ≥1 test.
- 3 corner stubs correctly NOT translated; all difficulty_instance cross-references resolve.
- 0 design instances skipped — every non-stub instance passed the PRD-first two-condition filter.

Verification: 57/57 collect cleanly (orchestrator confirmed with PYTHONPATH=.); every test carries exactly one resolving Design tag; all 70 quoted PRD citations survive whitespace-normalized grep; no scaffold leakage, no skip/xfail markers. Numeric assertions copied from design indices' pre-computed values (cost 174000/158000, confidence 0.83/0.50, invoice 95000, per-milestone line_total 13266 → billable 26532, DNA COUSIN@200, hours-cap at 3.0, ledger 43000/43000/0).

## Step 6: Generate implementation — 2026-07-07T11:47:58.000Z

Built Python + Flask implementation at workspace/implementation/. Source files (3): app.py (entire API), requirements.txt (flask==3.0.3), start.sh.

Endpoint count: 60/60 confirmed (35 POST + 25 GET), matching PRD §4 across 15 resource groups + _clock/set_current_utc.

Startup contract verified: start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec; pip install guarded. Storage in-memory only (14 module-level dicts); no seeding/preload; clock resets to 2026-03-01T00:00:00Z default each boot.

Correctness spot-checks passed against live server: envelope/pagination/auth/RBAC/not-found ordering; dual-variant project_cost; person_confidence + 2-verified-citation auto-verify cascade → project counter flip + cyclic dispute→reopen decrement; milestone_invoice_amount (PREMIUM 90000 +RUSH 5000, 7.5% agency fee, line_total 102125) + compensating cancel-after-invoice credit; appointment ordering (30-min buffer → capacity → interval); DNA subject-not-verified gate; hours hard cap (budget×1.5).

Interpretation decisions flagged: project version/updated_at bumped as secondary cascade only on counter/ledger increment ops (not pure read-time recomputations); FK existence checked (404) before general field validation (400), missing required FKs fall through to ERR_VALIDATION.

Orchestrator verified: test_helpers/, test_suite/, implementation/ all present; 57 tests collect cleanly.

## Step 7: Run tests and iterate — 2026-07-07T11:51:03.000Z

Ran as 2 sequential waves of 4 concurrent rounds each (host-saturation mitigation — four other pipelines concurrent on this host).

Iterations run: 1 (initial 2-wave, 8-round sweep passed clean; no further iterations).

Result: All 8 rounds passed 57/57 tests — passed=57 total=57 failed=0 errors=0 skipped=0 in every round, zero flakiness across the union of rounds. Orchestrator independently confirmed all 8 results.{1..8}.json show 57/57 failed=0 errors=0.

Tests deleted: None.
Fixes applied to test_helpers/: None.
Fixes applied to implementation/: None.

Host-saturation vs genuine failures: No ERRORs in any round despite four concurrent pipelines — the 2-wave (4-concurrent) sweep kept peak concurrency low enough to avoid boot-timeout noise. All 57 tests passed deterministically.

## Step 8: Finalize PRD — 2026-07-07T11:51:03.000Z

SKIPPED per skill skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits, so no PRD_FINALIZED.md is produced. Step 9 still runs.

## Step 9: Complete PRD — 2026-07-07T11:56:49.000Z

Produced workspace/PRD_COMPLETED.md (started from PRD.md since PRD_FINALIZED.md absent).

File sizes: PRD.md 268 lines/42,149 chars → PRD_COMPLETED.md 268 lines/43,466 chars (char delta +1,317; no line-count change — all in-paragraph inserts/revisions).

Counts: 5 ambiguity-pins, 2 mismatch-revisions across 4 edited paragraphs.

Changes:
- §2.8 Repository Scheduling Invariants — revise — mismatch — clock is settable but functionally inert in booking; booking checks compare windows directly (app.py:43,1474-1487,1550-1554).
- §3.1 Provisioning (Client) — insert — ambiguity — duplicate client email rejected with ERR_VALIDATION (400); ARCHIVED unreachable (no endpoint moves client out of ACTIVE) (app.py:450-453).
- §3.1 Provisioning (Researcher) — insert — ambiguity — duplicate researcher email rejected with ERR_VALIDATION (400) (app.py:482-484).
- §3.4 Citation state machine — insert — ambiguity — person version/updated_at advances only when citation create/verify/dispute changes verification_status (auto-verify/reopen), not for mere confidence recompute (app.py:764,799-809,825-835).
- §3.6 Repository visits (researcher buffer) — insert — ambiguity — buffer comparison strict; gap of exactly 30 min permitted (app.py:1476-1477).
- §3.6 Repository visits (capacity) — insert — ambiguity — strict overlap; sharing only an endpoint does not count (app.py:1484).
- §3.6 Repository visits (clock) — revise — mismatch — comparisons are proposed-window vs existing BOOKED windows; clock maintained/settable but not consulted (app.py:1474-1487,1547-1554).

Already-pinned (no change): three-guard booking order, invoice discount→surcharge→cap rounding, billable_amount_cents per-milestone rounding, DNA cM bands, person verify gate ordering, cancel-after-invoice credit ledger, project-active checks for record searches/time entries, DNA-cancel-on-project-close cascade.

Orchestrator verified PRD_COMPLETED.md present, PRD_FINALIZED.md correctly absent.

## Pipeline complete — 2026-07-07T11:56:49.000Z

All steps done. Final state: 57/57 tests pass across all 8 stability rounds (0 failures, 0 errors). Task task_0789_genealogy_research (Expert) is fully passing with PRD_COMPLETED.md as the finalized contract.
