# Worklog — task_0638_tanning_spray_tan_salon

## Step 1: Create task directory — 2026-06-23T11:07:58.000Z

Task directory `tasks/task_0638_tanning_spray_tan_salon` was pre-assigned and pre-created (workspace/ present). Step 1 max-index scan skipped per pipeline directive.

## Step 2: Generate scaffold (Expert band) — 2026-06-23T11:26:53.000Z

Generated all three Expert-band scaffold artifacts. All three files written and confirmed: SCAFFOLD.yaml (1169 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1016 lines), SCAFFOLD_CORNER_DESIGN.yaml (1443 lines).

Lint verdict: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. (424 calls scanned across §1.8 + §1.9.)

Complexity profile: primary archetype `temporal_windowing` + secondary `compliance_audit`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; flat topology; parallel state-machine shape; peer_roles; immediate consistency.

Counts:
- Entities (11): MembershipPlan, Member, Equipment, SprayRoom, ConsentRecord, Session, Product, RetailOrder, Payment, SalonLedger, MaintenanceLog
- State machines: 5 — Member.status (w/ FROZEN), Member.billing_status (parallel dimension), Session.status (cyclic reserve→cancel→reserve), Equipment.status (guarded/compound w/ MAINTENANCE), RetailOrder.status (forward + compensating refund)
- Calculations: 6 — uv_dose_allowed_seconds (dual-variant, nested-min), member_weekly_frequency (cooldown + minor/adult caps), freeze_proration_credit, upgrade_proration_charge, retail_order_total (per-line-then-sum rounding), equipment_service_due (threshold)
- Validations: 15 (priority-ordered)
- Endpoints: 43 (incl. 4 `/_` test-driving: `/_clock/set_current_utc` default 2026-01-01T00:00:00Z, `/_billing/charge-first-dues`, `/_billing/run-eft`, `/_billing/set-upgrade-outcome`)
- Error codes: 37
- Roles: 4 — Member (entity_backed:Member), FrontDeskStaff/SalonManager/BillingSystem (opaque)
- Concurrency rules: 1 — OCC on Member.version for upgrade-supersede
- §1.8 instance counts: 9 rule_ids × 2 = 18 instances
- §1.9 instance counts: 9 sections, 41 total (39 active + 2 excluded_because stubs)

Key notes: formula-derived assertions computed in Python and pinned as literals (dose 180/100/150, freeze credit 4000, upgrade charge 3340, retail subtotal 4945 with divergent sum-then-round 4946 making rounding-order observable). SERVICE_THRESHOLD = 2 for test reachability. api_prefix = `/` (flat topology). Hard Constraint honored — no sibling tasks read.

## Step 3: Copy shared files — 2026-06-23T11:27:12.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-23T11:33:14.000Z

Generated workspace/PRD.md (288 lines) from SCAFFOLD.yaml only.

Major sections: §1 Introduction; §2 Global Specifications (10 subsections: RBAC all 4 roles, fixed Response Structure, Pagination, Common Resource Properties [7 audit-tracked + 4 write-once], Money/Time/Rounding + logical clock, Parallel state dimensions & cascades, Nested retrieval/existence ordering, Validation ordering, OCC on membership changes, Salon Ledger invariant); §3 Business Logic (10 subsections, lifecycle-grouped, zero path leaks); §4 Endpoint Definitions (all 43 endpoints); §5 Error Code Catalogue (all 37 codes).

Hard Contract reports: Field coverage PASS (54/54 entity fields, 34/34 endpoint inputs, 7/7 query_params, 8/8 path_params). Rule coverage PASS (OCC, state machines, calculations, validation precedence, cascades all in prose). Path purity PASS (430 backtick tokens scanned, 0 path/method leaks in §3).

Confirmation: neither design YAML read; PRD generated purely from SCAFFOLD.yaml + doc-generator skill spec.

## Step 5: Generate unit tests — 2026-06-23T11:47:30.000Z

Generated test infrastructure: 8 test files, 75 tests total.

Test files: test_01_member_lifecycle.py (10), test_02_freeze_upgrade_cancel.py (8), test_03_billing_cycle.py (6), test_04_session_booking_dose.py (13), test_05_minor_uv_consent.py (2), test_06_session_run_equipment.py (22), test_07_retail_orders.py (10), test_08_rbac_and_errors.py (4).

Coverage (audited programmatically): Queue A (Difficulty §1.8) all 18 instances covered, each ≥2 tests → 36 difficulty-tagged tests. Queue B (Corner §1.9) all 39 non-stub instances covered, each ≥1 test → 39 corner-tagged tests. Skipped: the 2 `excluded_because:` stubs (errors/skin_type_uv_prohibited_standalone, errors/dose_exceeds_limit_standalone) correctly NOT translated — their cited difficulty instances own the assertions. No instances failed the PRD-first filter.

Verification: all 75 docstrings carry verbatim PRD citation; each test ends with exactly one resolvable Design: tag; no skip/skipif/xfail; py_compile clean; 75 tests collect under pytest.

test_helpers/ files: __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

## Step 6: Generate implementation — 2026-06-23T11:47:30.000Z

Generated Python + Flask implementation in workspace/implementation/.

Files: start.sh (foreground launcher, executable), requirements.txt (Flask==3.0.3), app.py (entry + all 43 routes + error handlers + validation precedence), auth.py (header extraction + RBAC, 4 roles), clock.py (logical clock default 2026-01-01T00:00:00Z), db.py (in-memory store + UUID), errors.py (38 error IDs + ApiError), response.py (meta/response_type/data envelope + pagination), pagination.py (limit/offset default 10/0, max 100), money.py (Decimal round_half_up + per-line retail), calc.py (dose schedule, ISO-week, freeze/upgrade proration, service threshold), repo.py (audit stamping, existence lookups, ledger singleton), serialize.py (serializers + is_minor recompute-on-read), timeutil.py (ISO 8601 UTC parse/format).

Dependencies: Flask==3.0.3 only; rest stdlib (decimal, datetime, uuid).

Contract confirmations: start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground exec python3 app.py. Storage in-memory only (Python dicts), no SQLite/disk/tmp; fresh boot all collections total_count=0, ledger 0, clock at default, nothing seeded (SalonLedger singleton lazy). Endpoints implemented: 43 (incl. /_clock/set_current_utc + /_billing/* simulators).

Self-test: 67 ad-hoc end-to-end checks all pass. One bug fixed during gen: member-ownership (require_self) moved to authorization tier (priority 2, before existence priority 3) per PRD §2.8 — foreign/nonexistent member id now returns ERR_FORBIDDEN 403 not 404.

## Step 7: Run tests and iterate to PASS — 2026-06-23T11:58:47.000Z

Iterations run: 2 (initial diagnostic sweep + one fix sweep).

Initial state: 73/75 passing deterministic across all 8 rounds — 2 real failing tests.

Tests deleted: None. Both failures were legitimate and traced to PRD-covered, uniquely-derivable rules.

Fixes applied to test_suite/ (STEP 2 — test bug):
- test_suite/test_04_session_booking_dose.py, test_spray_session_end_at_computed: assertion did brittle exact-string equality `end_at == "2026-06-15T11:05:00Z"` (no fractional digits), contradicting PRD §2.4's mandate that timestamps carry three fractional digits (impl correctly emits ...11:05:00.000Z). Added _instant() parse helper and changed assertion to compare parsed instants — faithful to PRD §3.4's value rule (end_at = start_at + requested_seconds) without over-constraining format.

Fixes applied to implementation/ (STEP 3 — implementation bug):
- workspace/implementation/app.py, start_session(): removed line `s["allowed_seconds"] = allowed` which overwrote the persisted reservation-time allowed_seconds at session start. Per PRD §3.4 allowed_seconds is populated once at reservation; §3.7/§3.8 only re-evaluate the dose check (requested_seconds <= allowance gate) at start, never rewriting the stored field. Recomputed allowance still used for the start-time gate; only the field overwrite removed. Persisted estimate now holds at 150 across start.

Final result: 8/8 parallel rounds clean, 75/75 tests passing each round. Storage in-memory only.

Orchestrator re-verification: re-ran the full 8-round foreground sweep independently (subagent had cleaned up its results files). All 8 rounds total=75 passed=75 failed=0 errors=0 skipped=0. results.{1..8}.json left in place under workspace/implementation/.

## Step 8: Finalize PRD — 2026-06-23T12:01:51.000Z

Produced workspace/PRD_FINALIZED.md. Step 8 ran (Step 7 had >0 fixes: 1 test_suite fix + 1 implementation fix).

Line counts: PRD.md = 288; PRD_FINALIZED.md = 288. One line modified in place (line 172); %-delta ≈ 0.35% (1/288).

Changes:
- §3.8 (Dose, Proration) — revise — Pinned that the persisted/serialized session allowed_seconds holds the reservation-time value and is NOT overwritten by the start-time re-evaluation (gate-only); restated it remains null for spray sessions — impl app.py:741 (reservation write), app.py:794-800 (start gate, no write-back), serialize.py:112 (emits stored value).

Step 7 diff item mapping:
1. test_suite fix (test_04 test_spray_session_end_at_computed) — No PRD edit. Pure fixture bug; relaxed assertion only brought test in line with rules PRD already pins (3-fractional-digit timestamps §2.4; end_at = start_at + requested_seconds §2.5/§3.4).
2. implementation fix (start_session dropped allowed_seconds writeback) — PRD silence → patched. PRD said dose ceiling "re-evaluated at start" but never stated whether persisted allowed_seconds is overwritten; edit pins start re-evaluation is pass/fail gate only, stored reservation-time value intact.

## Step 9: Complete PRD — full impl scan — 2026-06-23T12:10:26.000Z

Produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md via exhaustive impl scan. Always runs.

Source vs completed: PRD_FINALIZED.md 288 lines → PRD_COMPLETED.md 288 lines (in-paragraph edits only, no new sections). Chars 44,691 → 50,427 (+5,736).

Counts: ambiguity-pins 14, mismatch-revisions 4 (18 changes total).

Key changes: §2.2 api_request_id format + api_request_timestamp uses wall clock; §2.3 limit/offset clamping + tie-break + has_more formula; §2.4 version initial=1; §2.1 Member cross-owner fetch ERR_FORBIDDEN / list silent-filter; §3.1 weekly cap counts RESERVED/IN_PROGRESS/COMPLETED, plan_id required, is_minor whole calendar years; §3.2 first-dues/activation/run-eft ordering & shapes; §3.3 upgrade ACTIVE precondition + outcome consumption; §3.4 existence-vs-shape ordering; §3.8 turnaround≥0, retail discount whenever plan resolves; §3.9 lines non-empty + shape-before-resolution + paid-order ledger/Payment side effects; §3.10 payment not-found generic ERR_NOT_FOUND, ventilation buffer≥0; §4 /_billing/charge-first-dues returns 201.

PIPELINE COMPLETE — all 9 steps done. PRD_COMPLETED.md exists on disk. Final test state: 8/8 parallel rounds, 75/75 passing.
