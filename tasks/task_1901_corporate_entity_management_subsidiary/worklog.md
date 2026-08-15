# Worklog — task_1901_corporate_entity_management_subsidiary

## Step 1: Create Task Directory — 2026-08-14T23:46:00.000Z

Directory `tasks/task_1901_corporate_entity_management_subsidiary/` and `workspace/` pre-created by the pipeline invoker (per command args); orchestrator verified existence and did not compute or allocate any other index.

## Step 3: Copy Shared Files — 2026-08-14T23:46:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1901_corporate_entity_management_subsidiary/workspace/INSTRUCTION.md` (done concurrently with Step 2 subagent run, as the two steps touch disjoint paths).

## Step 2: Generate Scaffold — 2026-08-15T01:02:00.000Z

Done. All three scaffold artifacts are generated, lint-clean, and fully cross-verified.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1901_corporate_entity_management_subsidiary/`:

- **`SCAFFOLD.yaml`** — 13 entities, 68 endpoints, 10 state machines, 7 calculations, 10 ordered validation priorities, 60 error codes, 5 roles (all with `identity:`), 2 OCC concurrency rules. Archetype: compliance/audit + workflow orchestration; layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled actions; graph topology (self-referential ownership DAG + grant delegation chains); segregation-of-duties role model; logical clock with pinned startup default `2026-08-01T00:00:00Z` plus `/_clock/set_current_utc` and `/_system/sweep` test-driving endpoints.
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 19 instances, all 9 rules at ≥2 each (boundary has 3), each with structured, replayable `setup_api_calls` chains and pre-computed literal asserts.
- **`SCAFFOLD_CORNER_DESIGN.yaml`** — 63 active instances + 5 `excluded_because` stubs across all 9 claim-extraction sections; every one of the 60 error codes is exercised by at least one instance.

## Harder-than-expert design highlights

- **Dual-variant calcs in different domains**: franchise tax ESTIMATED (prior shares basis) vs ACTUAL (current shares) — 26000 vs 34500 on the same filing; ownership DIRECT vs LOOK_THROUGH (1000 vs 5000 bps on identical records).
- **Combinatorial formulas in different modes**: share-tiered tax with ceil/min/conditional (mode a); late penalty with pinned per-component round-half-up before summation — 12546 vs the non-conformant 12547 (mode b).
- **Two depth-3 transitive cascades** from different triggers: agent-resignation → posture → qualification REVOKED → filings WITHDRAWN; dissolution → appointments REMOVED → grants REVOKED → delegated grants REVOKED.
- **Two OCC true-races** (`ERR_STALE_VERSION`, 412) on `LegalEntity.version` for resolution adoption and ownership creation — both lint-verified to take `expected_entity_version` and bump the parent version.
- **Interval semantics contrast**: grant windows half-open (adjacency legal, overlap 409) vs agent-coverage windows where successor overlap is *mandatory* (gap 422); plus delegation window containment and a 10000-bps temporal aggregate cap.
- **Segregation of duties** keyed on `X-User-ID` across three control pairs (drafter/adopter, submitter/acceptor, suspender/reinstater), and validation priority conflicts pinned across distinct category pairs (state>safety; constraint>fiscal).
- ComplianceEvent append-only audit trail, posture derivation (`GOOD_STANDING/DELINQUENT/SUSPENDED/FORFEITED`) gating qualification/certificate operations, weekend-roll + leap-clamp due-date math, and compensating invariants pinned as formulas (fee-accrual ledger; active-grant count per tuple).

## Verification

`scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (1309 calls scanned, exit 0). Additionally verified programmatically: every assert literal computed by executing the formulas (tax/penalty/fee/date arithmetic all pass), zero unbound `${var}` placeholders, name uniqueness across all 87 instances, all enum values producible, no forbidden concurrency vocabulary, and correct three-file key split.

## Step 4: Generate PRD — 2026-08-15T01:20:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1901_corporate_entity_management_subsidiary/workspace/PRD.md`.

**Hard Contracts Reports**

Contract 1 — Field-Name Coverage:
- entities[].fields: 104 required, 104 present, 0 missing
- endpoints[].request_body / query_params / path_params: included in the 104, 0 missing
- Status: PASS

Contract 2 — Rule Coverage:
- validations[] with priority: 10 checked, 10 expressed in prose (§2.10), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (§2.7, §3.4, §3.11), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed, 0 missing
- validations[] conditions: 61 error IDs checked, all matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content: defaults, initial values, and enum values reconstructible from prose, 0 missing
- sibling-branch symmetry: parallel transitions (e.g., `SCHEDULED`/`PREPARED` → `WITHDRAWN`, `ACTIVE`/`SUSPENDED` → `REVOKED`) rendered with equal density, 0 asymmetric
- Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned: 583
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS

## Step 5: Generate Unit Tests — 2026-08-15T01:52:00.000Z

All checks pass. The suite is complete and structurally verified.

## Summary

Generated complete test infrastructure for `task_1901_corporate_entity_management_subsidiary`:

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — 17 enums + 13 TypedDicts; `ComplianceEvent` correctly carries only `id`/`created_at` (append-only, no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 methods, incl. `/_clock/set_current_utc` and `/_system/sweep`)
- `api_errors.py` — all 60 error IDs with the PRD §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py` (canonical J1/J2/J3 jurisdiction payloads), `constants.py`, `test_users.py` (opaque shared headers + `make_officer_headers`/`make_agent_headers` per-instance builders for the two entity-backed roles)
- `fixtures.py` — composite chains: `setup_base_entity` (jurisdiction→agent→draft→adopt formation resolution→submit→confirm), `appoint_officer` (resolution→sweep→EFFECTIVE), `create_grant`, `setup_entity_with_qualification`, `create_ownership_record` (fetches fresh OCC version), audit-trail readers

**Stage 2 — `test_suite/` (16 files, 100 test functions / 109 collected items):**
- 38 difficulty-tagged tests: all 19 §1.8 instances covered with exactly ≥2 tests each (tax ESTIMATED/ACTUAL divergence 26000/34500, block-ceil boundary 5000→17500 vs 5001→26000, pinned rounding order 12546-not-12547, grace-end boundary 0 vs 12512, both OCC rules, both cascades, both priority pairs, both cycles, etc.)
- 62 corner-tagged tests: every non-stub §1.9 instance covered ≥1×; all 5 `excluded_because` stubs verified to resolve to real difficulty instances and left untranslated

**Skipped instance (PRD-first filter):** `Corner/entities/entity_create_computed_fields_input_ignored` — the PRD never states whether client-supplied computed/system fields in a create body are ignored or rejected, so "201 with server-computed values" is not uniquely derivable. No placeholder emitted.

**Judgment calls under PRD-first:** `dissolved_entity_terminal_lockdown` asserts `ERR_ENTITY_NOT_ACTIVE` for PATCH-on-DISSOLVED (PRD §3.2 verbatim) rather than the instance's `ERR_ENTITY_ALREADY_DISSOLVED`, which contradicts the PRD; `deactivated_officer_blocks_appointment_adopt` asserts only the adopt path (double-deactivate rejection is not PRD-pinned); event payload shapes (e.g. `POSTURE_CHANGED` from/to fields) and `matching_grant_id` were dropped where PRD never names them; resolution version assertions use relative +1-per-mutation (PRD §2.4) instead of an absolute initial value PRD pins only for `LegalEntity`.

**Verification:** pyflakes clean; 109 items collect; every docstring carries a PRD citation with a ≥8-word substring surviving literal grep of PRD.md (100/100); every docstring ends with exactly one `Design:` tag resolving to a real instance; no skip/xfail markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-15T01:52:00.000Z

Implementation complete and verified. 

## What was built

A complete Python + Flask implementation of the Corporate Entity Governance API in `/home/ubuntu/github/CodingPRD/tasks/task_1901_corporate_entity_management_subsidiary/workspace/implementation/`:

- **`start.sh`** — executable foreground launcher; guarded dependency install (`import flask` check, so per-test reboots never re-run pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — app factory, blueprint registration, envelope-consistent error handlers (ApiError, 404, 405, 500).
- **`store.py`** — empty-at-boot in-memory stores (no seeding), logical clock pinned at `2026-08-01T00:00:00Z` until `POST /_clock/set_current_utc`, monotonic insertion sequence for deterministic `created_at` tie-breaks.
- **`errors.py` / `response.py` / `middleware.py`** — full error catalog with exact HTTP statuses, the `{meta, response_type, data}` envelope (list meta carries `limit/offset/total_count/has_more`), and `X-User-ID`/`X-User-Role` auth with entity-backed identity binding for `AuthorizedOfficer`/`RegisteredAgentUser`.
- **`services.py`** — all calculation rules (due-date with weekend roll and Feb-29 clamp, tiered/nonprofit/flat franchise tax with ceil blocks and cap, late penalty with per-component round-half-up before summation and the cap, expedited cert fee, posture derivation with suspension/forfeiture windows, look-through ownership with per-edge integer truncation and pinned BFS ordering), grant revocation cascades, resolution EFFECTIVE materialization (including `RESOLUTION_EFFECTIVE_BLOCKED`), filing generation (formation/qualification/rollover), lazy evaluation, and the system sweep with all seven counters.
- **`routes_*.py`** (9 modules) — all 60+ endpoints with the PRD §2.10 priority ladder: auth → role → path/body FK existence (404) → schema (400) → state gates (409) → OCC `expected_entity_version` (412) on resolution adopt and ownership create → segregation-of-duties/actor checks (403) → referential (422) → structural (409) → temporal (422) → monetary/aggregate caps (422).

## Verification

Exercised via three smoke suites run against `bash start.sh` cold boots (each phase passing on a fresh server: 99/99, 91/91, 25/25 checks), covering: envelope shapes, pagination bounds, all formation/dissolution transitions, ESTIMATED vs ACTUAL tax divergence, CALENDAR_DAYS vs BUSINESS_DAYS penalty intervals (1 vs 3 days on identical submit dates), fee accrual/reversal, period rollover, SoD on adopt/accept/reject/reinstate, agent resignation notice-ripening and the revocation cascade, qualification withdrawal cycle and exit clearance, delegation depth/window/limit rules, verify semantics with suspended delegators, certificate fees/issue/deny/auto-deny, ownership OCC/DAG/aggregate-cap/supersession/look-through math (8000×5000//10000 + 1000 = 5000 bps), and full dissolution cascade with audit events.

One implementation bug was found and fixed during testing (`suspended_since` type handling in posture derivation); the final tree boots cleanly from a fresh process with the default logical clock and an empty store.

## Step 7: Run Tests and Iterate — 2026-08-15T02:01:00.000Z

All 8 rounds pass 109/109 with zero failures. Clean exit achieved.

## Summary

- **Iterations run**: 2 (sweep 1: 108/109 in all 8 rounds, single deterministic failure; sweep 2 after fix: 109/109 in all 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1901_corporate_entity_management_subsidiary/workspace/implementation/routes_grants.py` — `create_grant()` delegator-validity check: removed the non-PRD `delegator["scope"] != scope` clause from the `ERR_DELEGATOR_GRANT_INVALID` condition. PRD §3.9 states only that "The delegator must be a direct grant — delegation depth is at most 2 — and must be `ACTIVE`", with violations mapped "respectively" to `ERR_DELEGATION_DEPTH_EXCEEDED` / `ERR_DELEGATOR_GRANT_INVALID` / `ERR_DELEGATOR_WINDOW_INSUFFICIENT` / `ERR_DELEGATION_LIMIT_EXCEEDED` — no scope-match requirement exists (the §3.9 verify read likewise checks the delegator only for ACTIVE status and window coverage). The extra clause fired at priority 7 and pre-empted the priority-8 depth check, causing `test_11_signature_grants_rules.py::test_delegation_depth_exceeded_rejected` (which delegates from an already-delegated grant using a different scope) to receive `ERR_DELEGATOR_GRANT_INVALID` instead of the PRD-mandated `ERR_DELEGATION_DEPTH_EXCEEDED`. The `status != "ACTIVE"` clause (PRD-verbatim, exercised by `test_15_state_gates.py::test_formation_pending_dissolution_blocked_delegator_invalid`) was preserved.

- **Key finding for generators**: the failure was an implementation over-constraint (scope-match on delegators) not traceable to any PRD sentence, not a test defect — the test traced verbatim to PRD §3.9 with unique derivability via the "respectively" error mapping.

## Step 8: Finalize PRD — 2026-08-15T02:10:00.000Z

Done. The finalized PRD is written at `/home/ubuntu/github/CodingPRD/tasks/task_1901_corporate_entity_management_subsidiary/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / %-delta**: PRD.md = 386 lines, PRD_FINALIZED.md = 386 lines. 0% line-count delta; exactly one line revised in place (+26 characters).

**Changes**:
- §3.9 (Signature Authority Grants and Delegation) — revise — the delegation-validity sentence now reads "The delegator must be a direct grant — delegation depth is at most 2 — and must be `ACTIVE` and belong to the same entity." (was: "...and must be `ACTIVE`.") — pins the same-entity requirement the implementation enforces on delegator grants — `implementation/routes_grants.py:75` (`if delegator["status"] != "ACTIVE" or delegator["entity_id"] != entity["id"]: raise_err(ERR_DELEGATOR_GRANT_INVALID, ...)`).

**Rationale for the minimal scope**: The Step 7 fix (removal of the non-PRD `delegator["scope"] != scope` clause) was an implementation over-constraint; PRD §3.9's exhaustive four-condition list with the "respectively" error mapping already uniquely determines that no scope-match requirement exists (Step 7's own key finding: "unique derivability"), so that aspect needed no PRD edit. However, the post-fix condition at the same site still rejects cross-entity delegation — a concrete behavioral choice the PRD did not uniquely determine (a fresh reader of PRD.md would not implement it). The pin appends "and belong to the same entity" to the existing `ACTIVE` clause, which is the clause mapped to `ERR_DELEGATOR_GRANT_INVALID` — exactly the error the impl raises for entity mismatch — leaving the four-condition/four-error "respectively" structure intact.

**Per-edit pre-edit search log** (single edit):
- (a) Subject: delegator-grant validity conditions at delegated-grant creation (PRD §3.9 delegation sentence).
- (b) Impl paths enumerated and read/grepped:
  1. `routes_grants.py:72-77` — create-time delegator status+entity check → `ERR_DELEGATOR_GRANT_INVALID` (the Step 7 fix site; wording matches it exactly).
  2. `routes_grants.py:87-89` — delegation-depth check (independent of entity; unaffected).
  3. `routes_grants.py:91-99` — delegator window containment and delegation-limit checks (independent; unaffected).
  4. `routes_grants.py:36-38` — body-FK existence for `delegated_from_grant_id` (existence-only, priority 3; the new clause is an additional later validity requirement, no conflict).
  5. `routes_grants.py:140-193` — `verify_grant()`: delegator checked only for `ACTIVE` + window coverage of `as_of_date`; creation-time same-entity enforcement means verify never encounters a cross-entity delegator, and the edit targets the creation sentence, not the separately-pinned verify paragraph (consistent).
  6. `services.py:289-301` (`revoke_grant` cascade), `services.py:304-309` (`revoke_officer_grants`), `routes_resolutions.py:235-240` (rescission/materialization grant cascades) — all cascade purely by id/foreign key with no delegator-validity semantics (unaffected).
  7. `routes_grants.py:117-130` (`list_grants` filters) — no validity semantics (unaffected).
  8. Test evidence: `grep` for `delegated_from` across `test_suite/` + `test_helpers/` confirmed every delegation scenario is same-entity; no test exercises cross-entity delegation, and no PRD sentence elsewhere contradicts the same-entity requirement.
- (c) Wording adjustment: appended "and belong to the same entity" to the existing clause rather than rewriting it, preserving the PRD-verbatim fragment "must be `ACTIVE`" (quoted in test docstrings) and scoping the requirement to the delegator of a newly created grant so the verify read and revocation cascades remain accurately described.

## Step 9: Complete PRD — 2026-08-15T02:25:00.000Z

All edits verified. The final file is complete and consistent with `implementation/`. Here is the summary.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 386 lines / 50,452 chars → `PRD_COMPLETED.md` 389 lines / 56,659 chars (**+3 lines, +6,207 chars**). 30 existing lines revised in place, 3 catalogue rows appended; no sections added or removed.

**Counts:** 30 ambiguity-pins, 5 mismatch-revisions (35 changes total across 30 diff hunks).

### Ambiguity-pins (PRD silent → pinned to impl)

- §2.1 — insert — ambiguity — unresolvable `X-User-ID` for `AuthorizedOfficer`/`RegisteredAgentUser` rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400) — middleware.py:30-33
- §2.2 — insert — ambiguity — `api_request_timestamp` drawn from the logical clock, not wall clock — response.py:18 + store.py:43-45
- §2.3 — revise — ambiguity — invalid `limit`/`offset` (non-integer, out of 1–100, negative) rejected with `ERR_INVALID_REQUEST`; sort ties broken by creation order; `has_more` = `offset + returned < total_count`; list endpoints accept exact-match equality filters applied before pagination with `total_count` counting the filtered set — response.py:46-80 + all list routes
- §2.10 — revise — ambiguity — body-schema/range violations (priority 4) rejected with `ERR_INVALID_REQUEST` (400) — middleware.py:45-54 + routes
- §3.1 — revise — ambiguity — `annual_report_due_day` range 1–31; penalty/fee/notice/forfeiture integer fields each ≥ 0 — routes_misc.py:91,102-112
- §3.1 — insert — ambiguity — deactivating a non-`ACTIVE` officer rejected with `ERR_OFFICER_NOT_ACTIVE` — routes_misc.py:240-241
- §3.2 — revise — ambiguity — `fiscal_year_end_month` 1–12 and `authorized_shares` ≥ 0 when supplied — routes_entities.py:52-53
- §3.2 — revise — ambiguity — confirm-formation on non-`FORMATION_PENDING` rejected with `ERR_ENTITY_NOT_FORMATION_PENDING` — routes_entities.py:152-154
- §3.3 — revise — ambiguity — agent-not-authorized-in-jurisdiction → `ERR_INVALID_REQUEST`; appointment on `DISSOLVED` entity → `ERR_ENTITY_ALREADY_DISSOLVED` — routes_appointments.py:50-55
- §3.4 — insert — ambiguity — drafting under `DISSOLVED` entity → `ERR_ENTITY_ALREADY_DISSOLVED`; per-type `payload` required-field schema pinned (`APPOINT_OFFICER`: officer_id/office_title/start_date; `REMOVE_OFFICER`/`ACCEPT_RESIGNATION`: appointment_id; `AUTHORIZE_QUALIFICATION`/`AUTHORIZE_WITHDRAWAL`: jurisdiction_id; `GRANT_SIGNATURE_AUTHORITY`: officer_id+scope; `REVOKE_SIGNATURE_AUTHORITY`: grant_id) — routes_resolutions.py:61-84
- §3.4 — revise — ambiguity — adoption with non-`ACTIVE` officer → `ERR_OFFICER_NOT_ACTIVE` — routes_resolutions.py:182-183
- §3.4 — revise — ambiguity — `RESOLUTION_EFFECTIVE_BLOCKED` event appended only on first blocked evaluation; resolution may still materialize later — services.py:330-337
- §3.4 — revise — ambiguity — `REMOVE_OFFICER`/`ACCEPT_RESIGNATION` with no-longer-`APPOINTED` appointment, and `REVOKE_SIGNATURE_AUTHORITY` with non-`ACTIVE`/`SUSPENDED` grant, still become `EFFECTIVE` with no effect — services.py:350-362
- §3.4 — revise — ambiguity — rescinding a non-`ADOPTED`/`EFFECTIVE` resolution → `ERR_RESOLUTION_NOT_ADOPTED` — routes_resolutions.py:218-220
- §3.4 — revise — ambiguity — rescinding `EFFECTIVE` `APPOINT_OFFICER` sets appointment `REMOVED` with `end_date` = current logical date and appends `OFFICER_REMOVED` — routes_resolutions.py:227-235
- §3.6 — revise — ambiguity — "entity still owes filings" defined: formation jurisdiction iff entity `ACTIVE`, else iff a `QUALIFIED`/`WITHDRAWAL_PENDING` qualification exists — routes_filings.py:154-159
- §3.8 — revise — ambiguity — appointment not covering/`ACTIVE` → `ERR_AGENT_COVERAGE_GAP`; applying on `DISSOLVED` entity → `ERR_ENTITY_ALREADY_DISSOLVED`; `AUTHORIZE_QUALIFICATION` payload must name the same `jurisdiction_id` — routes_qualifications.py:45-62
- §3.9 — revise — ambiguity — `GRANT_SIGNATURE_AUTHORITY` resolution payload must match `officer_id`+`scope` (else `ERR_REQUIRED_RESOLUTION_MISSING`); earliest-created match recorded as `source_resolution_id`; grant creation on `DISSOLVED` entity → `ERR_ENTITY_ALREADY_DISSOLVED` — routes_grants.py:57-71 + services.py:485-502
- §3.9 — revise — ambiguity — only `ACTIVE` grants transition to `EXPIRED`; `SUSPENDED` grants past expiry remain `SUSPENDED` — services.py:379-388
- §3.9 — revise — ambiguity — verify response carries `authorized`, `effective_limit_cents`, `matching_grant_id` (null when no match); invalid delegator → unauthorized with `effective_limit_cents` 0 — routes_grants.py:174-193
- §3.10 — insert — ambiguity — certificate request on `DISSOLVED` entity → `ERR_ENTITY_ALREADY_DISSOLVED` — routes_certificates.py:39-40
- §3.10 — revise — ambiguity — manual denial requires non-empty `reason`, else `ERR_INVALID_REQUEST` — routes_certificates.py:121-123
- §3.11 — revise — ambiguity — superseded record must be `ACTIVE` (else `ERR_OWNERSHIP_RECORD_NOT_ACTIVE`), is excluded from the new record's cycle and aggregate-cap evaluations, and creation increments the subsidiary's `version` — routes_ownership.py:102-119,137
- §3.11 — revise — ambiguity — chart response shape (`root_entity_id`, `nodes`{entity_id/depth/look_through_percentage_bps}, `edges`{parent_entity_id/subsidiary_entity_id/percentage_bps}); depth = minimum BFS discovery depth; each edge emitted once — services.py:554-597
- §3.12 — revise — ambiguity — dissolution-finalization appointment `end_date` set to the current logical date — routes_entities.py:240-243
- §3.13 — insert — ambiguity — posture persistence updates `compliance_posture`/`suspended_since`/`updated_at` without incrementing `version` — services.py:254-267
- §3.14 — insert — ambiguity — per-event-type `payload` key enumeration (filing_id, qualification_id, grant_id+optional reason, certificate_id, appointment_id, resolution_id, from/to_posture; empty for dissolution events) — services.py:102-113 + call sites
- §3.15 — revise — ambiguity — lazy evaluation applies to single-resource reads and mutation targets; list reads materialize only filing-overdue and grant/certificate-expiry evaluations — routes_filings.py:41-42, routes_grants.py:120-121, routes_certificates.py:66-67
- §3.15 — revise — ambiguity — clock adjustment accepts any ISO 8601 value (naive → UTC, backward moves allowed) and echoes the new reading as `current_utc` — routes_misc.py:51-65 + store.py:31-52
- §5 — insert — ambiguity — catalogue rows for framework fallthroughs `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — app.py:43-54

### Mismatch-revisions (PRD said X, impl does Y)

- §3.5 — revise — mismatch — officer-resignation grant-cascade cross-reference fixed from §3.8 (foreign qualification, no cascade defined) to §3.4 — routes_appointments.py:206 + services.py:304-309
- §3.7 — revise — mismatch — `ESTIMATED` basis fallback is the generation-time `shares_basis` snapshot (latest earlier-period accepted `FRANCHISE_TAX` preferred), not strictly "authorized_shares at formation-confirm time" — routes_filings.py:88-97 + services.py:420-428
- §3.8 — revise — mismatch — qualification first period selected by computed `due_date` ≥ current date, not by calendar-year "past" / "period containing today" — services.py:470-479
- §3.13 — revise — mismatch — posture derived on every *single-entity* read, not every read (entity list reads do not derive) — routes_entities.py:89-94
- §4 — revise — mismatch — harness endpoints `/_clock/set_current_utc` and `/_system/sweep` are mounted outside `/api`; prose now says so — routes_misc.py:51,68

**Verification:** every change traced to a specific implementation line read during the walk; no behavior invented; no new sections added; all edits are in-paragraph inserts/revisions except the three appended catalogue rows.
