# Worklog — task_0112_incident_management_oncall

## Step 1: Create Task Directory — 2026-06-03T00:00:00.000Z

Created `tasks/task_0112_incident_management_oncall/` and `tasks/task_0112_incident_management_oncall/workspace/` (pre-assigned index, no index-scan). Confirmed `./INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold — 2026-06-03T00:00:00.000Z

All three scaffold artifacts are written and the linter reports a clean verdict.

Generated the Expert-band scaffold for **task_0112_incident_management_oncall** (Incident Management & On-Call). All three required files written:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Structural counts**
- **Entities: 13** — Service, Responder, OnCallSchedule, ScheduleShift, EscalationPolicy, EscalationTier, MaintenanceWindow, Incident, PageAttempt, WarRoom, WarRoomMessage, Postmortem, ActionItem (flat topology, hub = Incident).
- **Endpoints: 54** (26 mutating actions + 28 GETs). The GET count is inflated by FK reverse-reachability (16 FKs each need a discovery GET) — this exceeds the 20–32 Expert guideline but is lint-clean, matching the documented "accept FK-reachability overage when clean" guidance; the GETs are all legitimate reads.
- **Errors: 34** (all referenced/triggerable). **Validations: 13** (priority-ordered). **Roles: 3** (PlatformAdmin/IncidentCommander opaque; ResponderUser entity_backed:Responder). **Concurrency rules: 1** (OCC `escalate-stale-incident` on Incident.version, 412).

**State machines defined: 5**
- Incident — parallel dimensions (lifecycle_status × escalation_status), escalation cyclic (ESCALATING→ESCALATING re-page loop).
- Postmortem — cyclic revert (DRAFT→IN_REVIEW→DRAFT) plus publish.
- ActionItem — linear + cancel, bubbles up to Postmortem.open_action_item_count.
- MaintenanceWindow — linear, activation cascades suppression.
- WarRoom — linear with cross-entity guard.

**Calculations: 9** — incident_sla_deadlines (dual variant calendar vs business_hours), error_budget_consumed (round-per-incident-then-sum), error_budget_event_cost, effective_sla_minutes (combinatorial nested min/max on posture), service_budget_status (threshold), paging_fanout, maintenance_window_spacing (closed+buffer), schedule_shift_overlap (half-open), escalation_target_selector (covering-shift selector with created_at tie-break).

**Difficulty design (§1.8): 19 instances** across all 9 §0.5 rules (≥2 each, distinct differentiation). **Corner design (§1.9): 33 instances** (30 active + 3 `excluded_because` stubs). `scaffold_lint.py` → `VERDICT: clean lint`.

## Step 3: Copy INSTRUCTION.md — 2026-06-03T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0112_incident_management_oncall/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T00:00:00.000Z

Generated `workspace/PRD.md` (296 lines). All hard-contract checks PASS (Contract 1 field-name coverage 56/56; Contract 2 rule coverage 0 missing across validations/OCC/state-machines/8 calculations/cascades; Contract 3 §3 path purity 0 violations). §2.2 verbatim from source. Withheld design files not opened.

**Section structure:**
- §1 Introduction — incident/on-call domain, two independent incident state dimensions, logical clock.
- §2 Global Specifications (10 subsections): RBAC (3 roles), Response Structure (verbatim), Pagination, Common Resource Properties, Logical Clock, OCC/Versioning (`expected_incident_version`, `ERR_STALE_VERSION`/412), Nested Retrieval & referential integrity, Validation Ordering (full 9-step priority), Precision & Rounding, Cascades & Reconciliation.
- §3 Business Logic (10 subsections): provisioning → incident trigger/first page → target selection & paging fan-out → ladder climbing/wrapping → SLA deadlines + both budget accountings → interval rules (shift vs window) → ack/resolve → maintenance suppression → war rooms → postmortems/action items.
- §4 Endpoint Definitions — 4-column table, 57 endpoints.
- §5 Error Code Catalogue — 2-column table, 34 error IDs.

## Step 5: Generate Unit Tests — 2026-06-03T00:00:00.000Z

Generated test infrastructure (`test_helpers/`, 9 files) and test cases (`test_suite/`, 6 test files + conftest, **68 test functions**), translating the two design indices (and only those) into pytest tests gated by the PRD-first two-condition filter.

**test_helpers/:** types.py, api_client.py (one method per PRD endpoint), api_errors.py (33 error IDs + HTTP-status map), assertions.py (per-entity; append-only logs carry only id+created_at), factories.py (input-only fields, unique-email defaults), constants.py, test_users.py (opaque vs entity_backed; make_responder_headers builder), fixtures.py (composite setup tiers), __init__.py.

**test_suite/:** test_01 SLA/budget calcs, test_02 state machines & cascades, test_03 validation-priority/boundary/cross-entity, test_04 temporal overlap & OCC, test_05 resource CRUD/validation, test_06 workflows/calcs/RBAC.

**Coverage:** Queue A (Difficulty) all 19 instances → exactly 2 tests each. Queue B (Corner) all 30 non-stub instances → ≥1 test each. **0 instances skipped.** 3 corner stubs correctly not translated; cross-refs resolve. Quality gates passed: no untagged/dual-tagged/orphan tags; every docstring ends with one Design: line; verbatim PRD citations; no skip/xfail; all 68 tests collect.

Note flagged: priority-pair difficulty instances anchored on PRD §2.8 (verbatim fixed evaluation order), each paired with an isolation test proving the lower-priority check is independently reachable.

## Step 6: Generate Implementation — 2026-06-03T00:00:00.000Z

Built Python + Flask in-memory implementation at `workspace/implementation/`. **All 54 PRD endpoints** (26 POST + 28 GET), 1:1 with the PRD table. ~2127 lines across 25 source files. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec, guards pip install on `import flask` check. In-memory dicts only (db.py); no SQLite/JSON/tmp; no seeding at startup (verified /services total_count=0 on fresh boot).

Behaviors verified via smoke suites: response envelope/error body/pagination; auth+RBAC; validation ordering; SLA calendar + business-hours variants; effective_sla_minutes tightening; paging fan-out channel order VOICE→SMS→PUSH→EMAIL with monotonic _seq tie-break; cyclic escalation ladder + OCC 412 + tier-wrap; ack_sla_breached; resolve cascade with round-per-incident-ceil-then-sum budget + event-cost + inclusive >= posture + service version bumps; maintenance suppression cascade; window spacing (closed, 30-min); shift overlap (half-open); postmortem revert + open_action_item_count bubble-up + publish gate; logical clock endpoint.

**PRD gap noted and handled:** error catalog (§5) has no not-found code for FK-only single reads `GET /escalation-tiers/{id}` and `GET /page-attempts/{id}`. Impl added `ERR_TIER_NOT_FOUND` / `ERR_PAGE_ATTEMPT_NOT_FOUND` (both 404) rather than misusing an unrelated code.

## Step 7: Run Tests and Iterate — 2026-06-03T00:00:00.000Z

**Iterations run:** 5 sweeps (1 baseline diagnostic + 4 verification, the last three all fully green).

Starting state: 63/68 passing, 5 deterministic failures across all 8 rounds. Final state: **68/68 passing in 3 consecutive clean 8-round sweeps (24 rounds, 1632 test executions, zero failures, zero errors)**, with tight uniform ~48s round durations and no restart-poll stalls.

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule and was uniquely derivable.

**Fixes applied to `test_suite/`:**
- `test_06_workflows_calculations_and_rbac.py` — added the missing `validate_paginated` import to the `from test_helpers import (...)` block. Two tests (`test_paging_fanout_one_attempt_per_enabled_channel`, `test_escalation_target_selector_picks_covering_shift`) used it without importing it, causing a `NameError`. It is a legitimate exported helper (used correctly in `test_05`).
- `test_01_sla_and_budget_calculations.py` — converted 3 SLA tests (`test_calendar_variant_ack_deadline_tier2_24x7`, `test_business_hours_variant_ack_deadline_tier1_skips_offhours`, `test_effective_ack_unchanged_on_healthy_service`) to build a full pageable topology via `setup_pageable_service` instead of bare `create_service` + `create_policy`. These are STEP-2 test bugs: PRD §3.2 states verbatim "If the policy has no tiers... the trigger fails the reachable-target check with `ERR_NO_ESCALATION_TARGET` (HTTP 409)." The tests' setup triggered an incident on a tier-less policy, so the PRD-faithful implementation correctly rejected the trigger before any incident existed to assert on. The fix makes the setup PRD-consistent (covering shift + tier-1) without weakening the assertions. The implementation's `ERR_NO_ESCALATION_TARGET` check was left untouched — it is PRD-required.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `app.py` — monkeypatched `socket.getfqdn` to short-circuit the unspecified-address (`0.0.0.0`) case to `localhost`, eliminating a ~5s reverse-DNS (PTR) stall that Werkzeug's dev server incurs during `server_bind` purely for its startup banner. Boot-to-ready dropped from ~7s to ~0.16s. Also silenced the Werkzeug access log. Both are cosmetic-only; responses are byte-identical and storage stays in-memory/empty on fresh boot.
- `start.sh` — gated the dependency check behind a `.deps_ok` filesystem sentinel and added a one-time `compileall` bytecode warm-up behind `.compiled_ok`, so the common per-test reboot spawns exactly one Python process (the server) instead of an extra cold interpreter for the `import flask` probe. The sentinels are build artifacts holding no entity data; the in-memory-only / no-seeding contract is preserved (verified `/services total_count=0` on fresh boot).

**Key finding:** All 5 original failures were genuine artifact bugs (one missing import, three PRD-inconsistent test setups) and are fixed. The subsequent intermittent "could not be restarted" errors were not logic failures but host-CPU-contention boot-timeout artifacts under the 8× concurrent per-test-reboot load (the documented flakiness pattern) — resolved by the getfqdn fix plus the single-process boot path.

**Orchestrator note:** Step 7's per-iteration `rm -f` had cleared the final `results.*.json`; orchestrator re-ran the 8-round sweep to regenerate and confirm the green artifacts — all 8 rounds 68/68 GREEN.

## Step 8: Finalize PRD — 2026-06-03T00:00:00.000Z

Ran (skip condition not met: Step 7 had test_suite/ + implementation/ fixes). Result: `workspace/PRD_FINALIZED.md` created as a **verbatim copy of PRD.md — 0 edits** (296 vs 296 lines, 0% delta, byte-identical confirmed by `diff`).

After locating each `<step_7_diff>` item in `implementation/`, none revealed a PRD silence or PRD/impl behavioral divergence:
1. test_06 missing `validate_paginated` import — pure test-file NameError; pagination fully pinned by PRD §2.3.
2. test_01 SLA tests rebuilt on `setup_pageable_service` — pure fixture-correctness fix; PRD §3.2 already states the tier-less-policy `ERR_NO_ESCALATION_TARGET`/409 rule verbatim; assertions unchanged; impl check untouched.
3. app.py `socket.getfqdn` monkeypatch + Werkzeug log silence — cosmetic only; binds 0.0.0.0, responses byte-identical, no API-observable behavior.
4. start.sh `.deps_ok`/`.compiled_ok` sentinels — build-artifact warm-boot optimization; no entity data, in-memory/no-seeding contract preserved.

Zero-edit outcome is valid and expected — all four diff items were pure test/build/cosmetic bugs.

## Step 9: Complete PRD — 2026-06-03T00:00:00.000Z

Full PRD-vs-`implementation/` scan from `PRD_FINALIZED.md` → `workspace/PRD_COMPLETED.md`. Source 296 lines / 43,963 chars → output 298 lines (+2 catalogue rows), char delta ≈ +2,300. **8 ambiguity-pins, 0 mismatch-revisions** (impl contradicted no uniquely-pinned PRD prose; all gaps were silences).

Per-change:
- §2.3 Pagination — insert — out-of-range `limit`/`offset` silently clamped (not rejected); non-integer → `ERR_INVALID_REQUEST` (422) — middleware.py:54-69
- §2.3 Pagination — insert — same-`created_at` list ties broken by insertion order — response.py:56 / db.py:11-15
- §2.5 Logical Clock — insert — reads real wall-clock UTC until pinned; `current_utc` 3 fractional digits; non-parseable `to_iso8601` → `ERR_INVALID_REQUEST` (422) — db.py:31-34, clock_routes.py:19-27
- §2.6 Concurrency — insert — escalate check order: shape `ERR_INVALID_REQUEST` → `ERR_INCIDENT_NOT_TRIGGERED` (409) → `ERR_STALE_VERSION` (412) — incidents_routes.py:132-142
- §2.7 Referential Integrity — insert — single-resource not-found codes `ERR_TIER_NOT_FOUND`, `ERR_PAGE_ATTEMPT_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND` (reused for missing shift) — lookups.py:34-62, schedules_routes.py:105-107
- §3.1 Provisioning — insert — duplicate `email` → `ERR_INVALID_REQUEST` (422) — responders_routes.py:28-30
- §3.2 Triggering — insert — `downtime_minutes` present on every incident representation, 0 until resolved — incidents_routes.py:49, serializers.py:111
- §3.8 Maintenance Windows — insert — `SCHEDULED` window with clock outside closed interval → `ERR_WINDOW_NOT_SCHEDULED` (409) — windows_routes.py:61-65
- §5 Error Catalogue — insert — added `ERR_TIER_NOT_FOUND` (404) and `ERR_PAGE_ATTEMPT_NOT_FOUND` (404) rows — errors.py:28-29

No remaining PRD silence or mismatch versus `implementation/`.

---

## Pipeline Complete — 2026-06-03T00:00:00.000Z

All 9 steps done. Final state: **68/68 tests passing across 8 clean parallel rounds** (regenerated artifacts `results.{1..8}.json` all GREEN). Task `task_0112_incident_management_oncall` (Expert, Incident Management & On-Call) is complete: 13 entities, 54 endpoints, 9 calculations, 5 state machines, 34 errors. Deliverables: SCAFFOLD + 2 design indices, PRD.md → PRD_FINALIZED.md (0 edits) → PRD_COMPLETED.md (8 ambiguity-pins), test_helpers/ + test_suite/ (68 tests), workspace/implementation/.
