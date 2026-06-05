# Worklog — task_0049_va_benefits

## Step 1: Create task directory — 2026-05-30 (pre-assigned dir)

Created `./tasks/task_0049_va_benefits/` with `workspace/` subdir. Index auto-scan SKIPPED per orchestrator instruction (3 sibling pipelines launching concurrently; directory pre-allocated to avoid collision). Verified `./INSTRUCTION.md` and `./skills/` present.

## Step 2: Generate scaffold — 2026-05-30

Generated all three scaffold artifacts; `scaffold_lint.py` returns VERDICT: clean lint (296 calls scanned, 0 violations, all FKs reverse-reachable). Files: SCAFFOLD.yaml (1126 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (878 lines), SCAFFOLD_CORNER_DESIGN.yaml (1127 lines). No design-key leakage into SCAFFOLD.yaml.

Complexity profile: primary archetype pricing_engine (non-linear VA combined-rating + MHA proration), secondary multi_party_negotiation (claim adjudication with remand/appeal cycles); flat topology; cyclic state-machine; peer_roles; difficulty band ~Advanced/Expert.

SCAFFOLD.yaml: 7 entities (Veteran hub, Claim, Condition, Dependent [common_fields:false], School, Enrollment, VocRehabPlan); 4 state machines (Claim cyclic appeal loop SUBMITTED→DEVELOPMENT→RATED→{GRANTED/DENIED}→REMANDED→DEVELOPMENT terminal CLOSED; Enrollment SUBMITTED→CERTIFIED→COMPLETED/CANCELLED w/ compensating slot restore; VocRehabPlan PROPOSED→APPROVED→COMPLETED/REJECTED; Veteran award lifecycle DRAFT↔ACTIVE↔SUSPENDED); 2 concurrency rules (OCC stale-version on Veteran award activate + Enrollment certify, both 412); 5 calculations (va_combined_rating whole-person non-linear + bilateral/provisional variants; monthly_compensation tiered base + dependent scaling ≥30 boundary; gi_bill_tier threshold tiers; housing_allowance estimated vs finalized pinned round-then-scale, rop>50 floor; yellow_ribbon_match waterfall match 100%-tier gate); 16 validations (priority-ordered, 8 categories); 39 endpoints; 16 error codes; 4 roles (ClaimsAdmin/RatingSpecialist/SchoolCertifyingOfficial opaque; Veteran entity_backed).

§1.8 Difficulty: 9 rule_ids × 2 = 18 instances, all numeric assertions pre-computed (combined [50,30]→70, [70,50,30]→90; comp(70,spouse)→182800; MHA tier-80 rop-75→120000; YR cap-bound 300000).
§1.9 Corner: 39 active + 6 excluded_because stubs (45 total) across all 9 claim-extraction-guide sections. All 62 instance names unique. api_prefix is `/` (flat); Dependent has filtered-list GET /dependents for reverse-reachability.

## Step 3: Copy INSTRUCTION.md — 2026-05-30

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-05-30

PRD generated at `workspace/PRD.md` (285 lines, 47744 bytes). Design files (DIFFICULTY/CORNER) confirmed withheld.

Structure: §1 Introduction (non-linear VA-math framing, 4 constituencies); §2 Global Specs (8 subsections: RBAC, response structure, pagination, common props/identifier resolution, precision/rounding, OCC, cascading recomputation, non-linear combined-rating principle); §3 Business Logic (15 subsections by benefit lifecycle); §4 Endpoint Definitions (38 endpoints, 4-col table); §5 Error Catalogue (16 errors).

Documented: 6 entities (Veteran, Claim, Condition, Dependent [version-less/updated_at-less], School, Enrollment, VocRehabPlan); 38 endpoints; 5 calculation formulas (va_combined_rating + 3 variants, monthly_compensation, gi_bill_tier, housing_allowance, yellow_ribbon_match); 4 state machines (Claim incl. cyclic appeal loop, Enrollment, VocRehabPlan, Veteran award); 16 errors; 2 OCC rules + claim grant/deny version guards.

Hard contract reports: field coverage 54/54 PASS; rule coverage (16 validations, 2 OCC, all transitions, 5 formulas) PASS; path-purity §3 (317 tokens, 0 path leaks) PASS.

Information-scattering: OCC split across §2.6 + owning workflows §3.4/§3.9/§3.12; three-hop grant cascade abstract in §2.7 then detailed in §3.4; calc constants embedded as business amounts (53,600 cents base, 1,095 days); validation precedence concentrated in §3.15 but each trigger also local to its operation; enrollment inputs split §3.11 (core) / §3.12 (Yellow Ribbon + version).

## Step 5: Generate unit tests — 2026-05-30 (concurrent w/ Step 6)

8 test files (7 modules + conftest.py); 75 test functions. Queue A (Difficulty): all 18 non-stub instances × 2 tests = 36. Queue B (Corner): all 39 non-stub instances × ≥1 test = 39. 5 instances skipped — all queue-B excluded_because stubs (no test_recipe; cited difficulty instance owns assertion): claim_appeal_cycle_covered_by_difficulty, monthly_compensation_dependent_ignored_below_30, combined_rating_nonlinear_covered_by_difficulty, enrollment_overlap_error_covered_by_difficulty, grant_cascade_chain_covered_by_difficulty. No active instances dropped by PRD-first filter. test_helpers/: __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py. All modules compile; 75 tests collect cleanly; 107 PRD citations verified verbatim; 0 skip/xfail; every docstring ends with one Design: line. Veteran entity-backed identity threaded via make_veteran_headers(veteran_id).

## Step 6: Generate implementation — 2026-05-30 (concurrent w/ Step 5)

12 files: start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground, sentinel-guards pip, frees stale listener), requirements.txt (flask==3.0.3), app.py (38 routes + error handlers), db.py (in-memory dicts, no seeding), errors.py (16 codes; ERR_INVALID_REQUEST=422 per this PRD), response.py (envelope, ISO-8601 UTC 3-digit Z, req_ id), middleware.py (X-User-ID/Role auth, role gate, entity-backed Veteran ownership), pagination.py (limit/offset/total_count/has_more, default 10/0, sort created_at ASC), util.py, calculations.py, services.py (cascade recompute), serialize.py (Dependent omits updated_at/version).

38 endpoints. Calc engine: Decimal + ROUND_HALF_UP; gi_bill_tier, va_combined_rating (efficiency reduction + bilateral variant + snap-to-10), monthly_compensation (step base + dependent additions gated ≥30), rate_of_pursuit, housing_allowance (two pinned rounding steps), yellow_ribbon_match (100%-tier only, half-of-uncovered capped, VA match). State machines: Claim (appeal loop MAX_REMANDS=2), Enrollment, VocRehabPlan, Veteran award. Grant cascade three-hop w/ per-entity version bump. Validation precedence per §3.15.

PRD ambiguities resolved (flagged for Step 8): (1) provisional_combined_rating_pct general recompute generalized to combined over all SERVICE_CONNECTED + conditions on RATED claims, floored at combined_rating_pct; (2) PATCH /veterans/{id} accepts but does NOT enforce expected_veteran_version (per §2.6 prose limiting OCC to activate/certify/grant/deny); (3) bilateral fractional subtotal sorted desc among integer ratings; (4) ERR_INVALID_REQUEST=422.

## Step 7: Test & fix loop — 2026-05-30

Step 7 subagent (long-lived) ran 2 iterations and reported a clean 8-round parallel sweep (75/75 ×8). Tests deleted: NONE (no PRD-coverage/unique-derivability failures). test_helpers/ fixes: NONE. implementation/ fix: app.py __main__ — replaced app.run() with werkzeug.serving.make_server(...).serve_forever() and short-circuited socket.getfqdn to dodge a ~5s DNS timeout on .local hostname resolution that was blocking bind under the per-test-server 15s restart budget. (Pure boot-perf; no behavioral/logic change, no PRD silence/mismatch revealed.)

### Orchestrator independent verification + launcher-resilience fix — 2026-05-30

The Step 7 subagent cleaned up its results.{1..8}.json, so the orchestrator re-ran the 8-round sweep to (a) regenerate the required artifacts and (b) independently confirm. First re-run: 75/75 ERROR ("API server ... could not be restarted") in ALL 8 rounds — NOT logic failures, pure setup/boot timeouts. Root-caused as host oversubscription: the orchestrator note warned 3 sibling pipelines run concurrently; with my 8 rounds + siblings' 8-round sweeps, the 14-core host is ~32× oversubscribed and per-test boots exceed the harness's fixed 15s restart budget.

Evidence gathered: (i) single isolated boot via the EXACT runner restart path = 0.25–0.53s success (server healthy, 404 on `/`); (ii) runner health-check accepts ANY HTTP response, so failure ⇒ server simply not listening within 15s; (iii) the runner sends server stdout/stderr to DEVNULL, so a boot crash would look identical to a slow boot — reproduced with stderr captured: no crash. Conclusion: implementation is logically correct; failures are environmental boot-capacity under concurrent-pipeline load.

CORRECTED ROOT CAUSE (the lsof/contention hypothesis above was WRONG): the 75/75 "could not be restarted" failures were caused by the ORCHESTRATOR'S OWN start-command form, not the implementation and not contention. The runner's `pytest_plugin._restart_server` re-derives the per-test working directory by regex-parsing the `--start-command` string: `_parse_command("bash start.sh")` finds no `cd … &&` prefix → returns cwd=".", which for the pytest subprocess is the PROJECT ROOT, not the implementation dir. `bash start.sh` then fails (no start.sh in project root) on EVERY per-test restart → 75/75 errors, each hitting the full ~15s timeout (round duration 1160s = 75×~15.5s). My manual isolated boot tests passed only because the shell had `cd`'d into the implementation dir, masking the bug. The Step 7 subagent's clean sweep was REAL — its prompt used the correct form `cd {impl} && bash start.sh`. I had dropped the `cd` prefix.

Resolution: (1) REVERTED both misdiagnosis-driven edits — `start.sh` restored to the original lsof+bind-probe launcher; `app.py` __main__ restored to Step 7's `make_server(...).serve_forever()` (Step 7's getfqdn/make_server DNS fix retained — that was a real Step 7 fix, untouched). Implementation now byte-identical to the Step 7-verified state. (2) Re-ran the 8-round sweep with the CORRECT `--start-command "cd {impl} && bash start.sh"`.

FINAL VERIFICATION — clean 8-round parallel sweep (run bq0qrl2tt): all 8 rounds 75/75 PASS, 0 failed, 0 errors, ~51s/round. results.{1..8}.json artifacts present and all passing. Implementation confirmed correct; the only genuine Step 7 change is the non-behavioral boot fix (app.py make_server/getfqdn).

Net Step 7 diff for Step 8: 0 tests deleted, 0 test_suite/ fixes, 0 test_helpers/ fixes, 1 implementation/ fix (app.py __main__ — boot/serving-layer only, no behavioral logic, no PRD silence/mismatch).

## Step 8: Finalize PRD — 2026-05-30

Ran (not skipped — Step 7 had 1 implementation/ fix). Result: PRD_FINALIZED.md byte-identical to PRD.md (285 lines each, MD5 95aaa3db5071a9b0b96b31a9a4e2b661 both). ZERO edits — correct outcome. The sole Step 7 fix (app.py:933-952 __main__ make_server/getfqdn boot change) is a process-startup/WSGI-serving-layer change with no observable HTTP request/response difference; PRD documents HTTP behavior only, not launch mechanism, so there was nothing to pin. Subagent applied NO-NEW-MISMATCH pre-edit search (subject = launch/serving mechanism; enumerated app.py:933-952, start.sh, db.py, middleware/serialize/services/calculations + all @app.route handlers; grepped PRD for getfqdn|make_server|threaded|0.0.0.0|PORT|werkzeug — only §2.6 app-level OCC matched, unrelated) and correctly declined to invent a launch/threading clause.

## Step 9: Complete PRD — 2026-05-30

Full PRD-vs-implementation scan. Source PRD_FINALIZED.md (285 lines, 47744 chars) → PRD_COMPLETED.md (285 lines, 48396 chars, +652 chars). 3 ambiguity-pins, 0 mismatch-revisions.
- §3.6 — insert — ambiguity — provisional_combined_rating_pct recompute scope: combined over all SERVICE_CONNECTED conditions + PROPOSED conditions of EVERY claim currently in RATED (not just the one rated), then floored at max(prov, combined_rating_pct) — services.py:73-91.
- §3.7 — insert — ambiguity — bilateral fold ordering: fractional bilateral-with-factor figure sorted descending together with integer non-bilateral ratings, efficiency reduction walked with no per-step rounding — calculations.py:156-157.
- §3.11 — insert — ambiguity — optional tuition_charged_cents defaults to 0 when omitted — app.py:674.
Flagged items dispositioned: (2) PATCH /veterans/{id} no OCC — already pinned by existing §2.6 sentence, no edit; (4) ERR_INVALID_REQUEST=422 — already in §5 table line 273, no edit. Broad scan found computed-field shapes, cascade ordering, remand-no-provisional-recompute, YR slot-restore gating, activation guard order, half-open overlap, GI Bill thresholds, validation precedence all already pinned. received_date "effective-date priority" prose has no impl footprint (never consumed) — left untouched.

## PIPELINE COMPLETE — 2026-05-30

All 9 steps done. Final 8-round per-test-server stability sweep: 75/75 PASS in every round (results.{1..8}.json present, all clean). Artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml; workspace/{PRD.md, PRD_FINALIZED.md (=PRD.md), PRD_COMPLETED.md (+3 ambiguity-pins), INSTRUCTION.md, implementation/}; test_helpers/ (9 files) + test_suite/ (7 modules + conftest, 75 tests). Implementation byte-identical to Step 7-verified state (orchestrator's transient launcher edits reverted after the 75/75-error detour was traced to an orchestrator-side --start-command form error, NOT an impl/test defect).
