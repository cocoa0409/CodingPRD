# Worklog — task_0365_sign_fabrication_installation

## Step 1: Create Task Directory — 2026-06-15T02:33:51.000Z

Created `tasks/task_0365_sign_fabrication_installation/` and `tasks/task_0365_sign_fabrication_installation/workspace/`. Task ID pre-allocated; no auto-scan performed.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-15T02:52:38.000Z

All three scaffold files generated and pass scaffold_lint.py cleanly (VERDICT: clean lint; 572 §1.8/§1.9 calls conform to §1.5; all 17 FKs have reverse-reachability).

Complexity profile: Workflow-orchestration primary + quota/allocation secondary (crew/equipment booking); layers = cascading side-effects, dual-variant calculation, optimistic concurrency, scheduled/deferred (clock-driven expiry). Topology hybrid; state-machine shapes cyclic + branching + compound.

SCAFFOLD.yaml (§1.0–§1.7):
- 12 entities: SignProject, ArtProof, Estimate, SiteSurvey, Permit, FabricationWorkOrder, InstallJob, Crew, Equipment, ChangeOrder, WarrantyClaim, Reorder
- 10 state machines including cyclic ArtProof revision loop, branching QC fork on FabricationWorkOrder, compound SignProject phase machine, FAILED-reschedule loops on InstallJob
- 2 concurrency rules (OCC on SignProject.version for estimate-accept and change-order-apply)
- 6 calculations: estimate_total (tiered pricing, pinned illum→rush rounding order), change_order_delta (forward-looking rescope), equipment_requirement (height/obstruction threshold), contract_total (aggregation), warranty_coverage (strict-boundary day window), permit_fee (lookup table)
- 12 validations (priority-ordered, 8 categories), 60 endpoints, 24 error codes, 5 roles (ShopManager, Designer, Customer, Surveyor, PermitClerk — all opaque, peer-role model)
- api_prefix set to root (""); cross-aggregate FKs given top-level fetch + filtered-list GETs

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 rule_ids × 2 = 18 instances, all formula-derived asserts pre-computed as literals (e.g. estimate 24300 / 74106 / 81500, CO delta +7200 / −36500, contract 31500, warranty strict-< boundary at 2026-08-30T10:00Z, LADDER inclusive 20 ft edge).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 9 sections, 43 instances (36 active with full test_recipes + 7 excluded_because stubs pointing at named §1.8 instances). All 61 instance names unique across both design files; no forbidden concurrency vocabulary.

## Step 3: Copy INSTRUCTION.md — 2026-06-15T02:52:38.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T02:57:51.000Z

Generated `workspace/PRD.md` (280 lines) from SCAFFOLD.yaml only (both design files withheld; confirmed not opened).

Structure: §1 Introduction (2 paras); §2 Global Specs (10 subsections: RBAC, verbatim Response Structure, Pagination, Common Properties/Versioning, Hierarchical Consistency/lazy reconciliation, Nested Retrieval ordering, OCC, Monetary Precision, Permit-Requirement/Illumination, Booking Integrity); §3 Business Logic (9 lifecycle subsections incl. validation-ordering + test-clock scattering zone); §4 62-endpoint table (4 cols); §5 24-error table (2 cols).

Coverage: all 13 entities, all 62 endpoints, all 24 errors. Hard Contracts: Contract 1 (Field-Name Coverage) PASS (63/63 fields, 4/4 input ids, 12/12 query params); Contract 2 (Rule Coverage) PASS (26/26 transitions across 9 machines, 2/2 OCC, 6/6 calculations precise, validation priority chain expressed, sibling-branch symmetry rendered); Contract 3 (§3 Path Purity) PASS (372 backtick tokens scanned, 0 path/method leaks). §2.2 emitted byte-for-byte from canonical source.

## Step 5: Generate Unit Tests — 2026-06-15T03:08:47.000Z

Generated test infrastructure translating exclusively from the two design indices (design-index-only contract honored).

Test files (7 + conftest): test_01_projects_and_crud.py (11), test_02_state_machines.py (11), test_03_pricing.py (10), test_04_surveys_permits_fabrication.py (8), test_05_install_scheduling.py (16), test_06_change_orders_warranty_reorder.py (15), test_07_listing.py (1).

Counts: 72 test functions total. Queue A (Difficulty): 36 tests — all 18 instances (9 rules × 2) covered with exactly 2 tests each. Queue B (Corner): 36 tests — all 36 non-stub instances covered with 1 test each. Skipped: 7 instances, all excluded_because: stubs (category: stub — cited difficulty instance owns the assertion). No instances dropped for PRD-coverage failure — every non-stub instance had verbatim, uniquely-derivable PRD prose.

test_helpers/ (9 files): __init__.py, types.py (11 entity TypedDicts + enums), api_client.py (one method per endpoint incl. /_clock/set_current_utc), api_errors.py (24 error IDs + HTTP status map), assertions.py (per-entity + contract-ledger invariant), factories.py (per-entity input-only payloads), constants.py (pricing/permit/equipment/warranty constants), test_users.py (5 opaque-role headers), fixtures.py (lifecycle composites + crew/equipment registration + clock control).

Verification: all files compile; every Difficulty tag appears exactly twice, every non-stub Corner tag exactly once; uncovered set equals precisely the 7 stubs; 18 spot-checked PRD citations verbatim-present; literal expected values (74106 total, 20406 surcharge, −36500 delta, 31500 ledger, 90-day exclusive warranty boundary, 20 ft inclusive ladder edge) copied verbatim and independently recomputed.

## Step 6: Generate Implementation — 2026-06-15T03:08:47.000Z

Built Python + Flask implementation at workspace/implementation/.

Files: start.sh (foreground; reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask==3.0.3), core.py (in-memory Store = 12 dicts keyed by id, logical clock, UUID/ISO-8601-UTC helpers, round_half_up via Decimal, error catalog, response-envelope builders), domain.py (pricing constants, price_estimate, equipment_class_required, lazy-expiry reconciliation, common-field stamping, serialization stripping internal _-fields), guards.py (auth/RBAC via X-User-Role, body validators, left-to-right existence, pagination), app.py (all routes, error handlers, state machines, calculations).

Coverage: all 12 entities, all ~60 endpoints incl. cross-aggregate fetches/filtered lists and /_clock/set_current_utc. Envelope: meta{api_request_id, api_request_timestamp, +pagination}, response_type, data. All 24 error IDs with correct HTTP codes.

State machines: cross-entity bubble-ups bump project version+updated_at; cancel/supersede cascades and change-order 3-hop cascade (apply → cancel in-flight WO → new RELEASED WO + phase reset to FABRICATION). Calculations: pinned-order surcharge rounding (illum before rush, each round_half_up separately) verified (74106); change-order delta verified (24300→31500, delta 7200); equipment thresholds (8/20 ft inclusive, obstruction→BUCKET_TRUCK); permit-fee table; warranty strict-< boundary 365/1825/90 days. Equipment overlap half-open [start,end); crew overlap same-day + 60-min buffer (CREW_BUFFER_MIN=60). Bookings conflict only against active (SCHEDULED/DISPATCHED) jobs. OCC: expected_sign_project_version mandatory on accept/apply, checked LAST → ERR_STALE_VERSION (412). Validation ordering: 401→403→404→422→409→business→412.

Storage: in-memory only — no sqlite/JSON/pickle/tmp/file I/O; no seeding/preloading at startup; every db write inside a route handler. Fresh boot empty store; binds 0.0.0.0; serves within ~3s.

## Step 7: Run Tests and Iterate — 2026-06-15T03:42:00.000Z

Iterations run: Diagnosed and fixed across multiple 8-round sweeps; converged after eliminating two distinct flakiness sources. Final stability proof: 6 consecutive clean 8-round parallel sweeps (48 rounds, 72/72 tests each, zero failures), plus cold-start/state-reset verification.

Tests deleted: None. No test was PRD-silent or non-uniquely-derivable.

Fixes applied to test_suite/:
- test_02_state_machines.py → test_second_proof_approval_when_one_already_approved_rejected: STEP 2 fixture/setup fix. The test approved proof_a (which bubbles the project DESIGN→ESTIMATING per PRD §3.1), then tried to submit proof_b — but submission is only valid while the project is still in DESIGN (§3.1), so proof_b could never reach SUBMITTED and the second-approval attempt returned ERR_INVALID_STATE instead of ERR_PROOF_ALREADY_APPROVED. Reordered the setup so both proofs are submitted while the project is still in DESIGN, then proof_a is approved, then the already-SUBMITTED proof_b's approval correctly trips the ERR_PROOF_ALREADY_APPROVED guard. Rule is verbatim-covered by PRD §3.1; implementation was already PRD-faithful (state check precedes business check per §3.9), so the fix made the test more faithful, not the implementation weaker.

Fixes applied to test_helpers/: None.

Fixes applied to implementation/ (server-robustness only — no PRD-traced behavior changed):
- requirements.txt / app.py _serve(): Switched HTTP server from Flask's dev server to waitress. Flask dev server (app.run(threaded=True)) dropped connections under 8× concurrent load (BadStatusLine / empty replies). Waitress serves concurrent connections reliably. Listening socket pre-created with SO_REUSEADDR+SO_REUSEPORT, bound via short retry loop so a port still in TIME_WAIT from the previous per-test server never fails rebind; channel_timeout/cleanup_interval reap idle keep-alive channels; threads=4.
- start.sh: Replaced per-boot python3 -c "import flask, waitress" probe (spawned a second interpreter on every per-test restart, doubling boot cost) with a one-time .deps_installed filesystem sentinel (build artifact, not entity state). Steady-state boot is now a single exec python3 app.py, removing the "API server could not be restarted" timeouts under CPU saturation. In-memory-only storage and full state reset on reboot preserved and verified.

The original implementation's domain logic (pricing, state machines, RBAC, validation ordering, OCC, booking conflicts, warranty windows) was already correct — every failure resolved was either a test-setup mistranslation or a server-lifecycle/HTTP-layer robustness issue, not a business-rule defect.

## Step 7 (resume re-confirmation) — 2026-06-15T03:42:00.000Z

Pipeline resumed after a transient API error (`ConnectionRefused`); no logic problem. Re-confirmed Step 7 green by deleting any stale results and running ONE fresh 8-round parallel per-test-server sweep via the long-lived fix subagent. Verbatim subagent summary:

- Iterations run: 1 (single fresh 8-round parallel sweep; re-confirmation of a previously-converged run).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

8-ROUND SWEEP: all 8 rounds passed (72/72 tests each). On-disk verification: results.1.json–results.8.json each report passed=72 total=72 failed=0.

## Step 8: Finalize PRD — 2026-06-15T03:42:00.000Z

PRD_FINALIZED.md was produced by the interrupted run's Step 8 subagent (its in-context summary was discarded on the crash). Per resume protocol, the orchestrator verified the existing artifact rather than regenerating a complete, valid output. Verification result: `workspace/PRD_FINALIZED.md` is a complete, intact 280-line PRD (full §1 Introduction → §2 Global Specs → §3 Business Logic → §4 endpoint table → §5 error table) with NO leaked tool/XML markup (grep for `</invoke>`, `</content>`, `<parameter>`, `function_calls`, `antml` → zero hits). `diff PRD.md PRD_FINALIZED.md` is empty: PRD_FINALIZED.md is byte-identical to PRD.md — a zero-edit minimal patch. This is the correct Step 8 outcome here: Step 7's only `implementation/` fixes were server-lifecycle/HTTP-layer robustness changes (Flask dev server → waitress; per-boot dep probe → `.deps_installed` sentinel) plus one `test_suite/` setup reorder — none of which changed PRD-traced behavior — so there was no PRD silence or PRD/impl mismatch for Step 8 to pin. Artifact kept as-is (not regenerated).

## Step 9: Complete PRD (completeness scan) — 2026-06-15T03:42:00.000Z

Ran the full PRD-vs-`implementation/` completeness scan starting from `workspace/PRD_FINALIZED.md`, producing `workspace/PRD_COMPLETED.md` (verified intact: 280 lines, full §1→§5 structure, no leaked tool/XML markup). Verbatim subagent summary:

- Source file (PRD_FINALIZED.md): 280 lines, 42203 chars. PRD_COMPLETED.md: 280 lines, 46887 chars. Char-delta: +4684. (All edits were in-paragraph; line count unchanged.)
- Counts: ambiguity-pins: 11, mismatch-revisions: 3.
- §2.1 User and RBAC — revise — mismatch — `X-User-ID` was stated as a mandatory header but impl only validates `X-User-Role`; revised to say `X-User-ID` is never inspected/required and has no effect — guards.py:15-22.
- §2.3 Pagination — insert — ambiguity — pinned bounds enforcement: empty/absent falls to default; non-integer, `limit` <1 or >100, or negative `offset` rejected with `ERR_INVALID_REQUEST` — guards.py:134-152.
- §2.3 Pagination — revise — ambiguity — ordering pinned to a stable monotonic creation sequence (ties broken by creation order, not timestamp string) and `has_more = offset + page_len < total_count` over full filtered set — app.py:68-73, core.py:177-184, domain.py:45.
- §3.1 Design loop — insert — ambiguity — `reject_reason` is optional (stored null when omitted, must be a string otherwise; non-string → `ERR_INVALID_REQUEST`) — app.py:242-246.
- §3.2 Estimates — insert — ambiguity — `ERR_REFERENCE_NOT_ELIGIBLE` also covers a non-existent or mis-parented proof (not `ERR_NOT_FOUND`) — app.py:264-266.
- §3.4 Fabrication release — insert — ambiguity — pinned release `PERMITTING`-state requirement and the required-permit-kind derivation (`STRUCTURAL` unless `COUNTY_C`; `ELECTRICAL` if illuminated; gate skipped when `permit_required` false; survey gate satisfied by any PASSED) — app.py:483-513.
- §3.5 Scheduling (equipment class) — revise — ambiguity — obstruction input is the most-recently-created PASSED survey's `overhead_obstruction`, treated as false when no PASSED survey exists — app.py:727,779-784.
- §3.5 Scheduling (equipment validation) — revise — ambiguity — pinned `LADDER` requirement (reach-only, no class constraint), non-existent-equipment error, and `NONE`-class-with-equipment_id behavior; also added that `in_service` is not enforced at scheduling — app.py:730-747.
- §3.5 Scheduling (registration) — revise — mismatch — `in_service=false` was stated as "unbookable" but impl never checks it; revised to informational-only — app.py:698-776 (no `in_service` check).
- §3.5 Scheduling (booking checks) — revise — ambiguity — pinned "active jobs" = `SCHEDULED`/`DISPATCHED`, 60-minute crew buffer, same UTC calendar date semantics, and equipment-check-before-crew-check ordering — app.py:671-695,749-760, domain.py:24.
- §3.5 Scheduling (references) — revise — ambiguity — window-coherence is body validation preceding referential checks; non-existent/mis-parented WO and non-existent crew → `ERR_REFERENCE_NOT_ELIGIBLE` (not `ERR_NOT_FOUND`) — app.py:711-724.
- §3.6 Change orders (proposal) — insert — ambiguity — proposal is not phase-gated and `delta_total_cents` is 0 when no accepted estimate exists — app.py:870-895.
- §3.6 Change orders (apply) — revise — mismatch — substrate update targets the accepted estimate snapshot (not the project) and the replacement WO snapshots the accepted estimate's `total_cents` un-adjusted by the delta; no-WO case leaves phase as-is — app.py:953-984.
- §3.7 Warranty — insert — ambiguity — install-job reference must exist/belong/`INSTALLED` else `ERR_REFERENCE_NOT_ELIGIBLE` — app.py:1012-1014.
- §3.8 Reorders — revise — mismatch — clone copies far more than "sign-type and dimension fields" (customer_name, site_address, jurisdiction_code, illuminated, rush, permit_required); `approved_estimate_id` null and `quantity` not carried onto the project — app.py:1116-1132.
