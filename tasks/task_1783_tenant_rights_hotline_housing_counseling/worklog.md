# Worklog — task_1783_tenant_rights_hotline_housing_counseling

## Step 1: Create Task Directory — 2026-08-14T15:54:00.000Z

Task directory `tasks/task_1783_tenant_rights_hotline_housing_counseling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (Step 1 treated as DONE per invocation instructions; no index scan performed).

## Step 3: Copy Shared Files — 2026-08-14T15:55:11.549Z

Copied `./INSTRUCTION.md` to `tasks/task_1783_tenant_rights_hotline_housing_counseling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T16:53:20.775Z

All checks pass and the lint is clean. The scaffold package is complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1783_tenant_rights_hotline_housing_counseling/`):
- `SCAFFOLD.yaml` — 1333 lines (§1.0–§1.7; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 862 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1691 lines (single top key `scaffold_corner_design`)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1181 calls scanned; 55 endpoints; 15 entities; 19 §1.8 + 63 non-stub §1.9 instances.)

**Counts:**
- Entities: **15** (Jurisdiction, RightsScript, SelfHelpResource, Counselor, Interpreter, Caller, ConsentRecord, CallSession, Case, CaseNote, FollowUp, LegalAidOrg, Referral, RetentionPolicy, PurgeJob) — top of the Expert band
- State machines: **12** entries (10 with transitions; Caller and CaseNote are explicit no-machine/append-only entries); non-linear shapes: Case (cyclic escalation loops + auto-escalation), CallSession (parallel session_status × interpretation_status dimensions), Referral (DECLINED→PROPOSED re-route loop), SelfHelpResource (CURRENT⇄OUTDATED cycle), RightsScript (revert loop)
- Calculations: **12** (incl. dual-variant case score PROVISIONAL/VERIFIED, dual-variant analytics RAW/DEDUPLICATED, pinned per-component rounding deposit exposure, circular-break follow-up cadence, buffered half-open interpreter overlap, ISO-week aggregate capacity, gapless script window chain, 4-level retention precedence, strict-> consent TTL)
- Validations: **12** priority rows (auth → SoD → existence → schema → OCC → state → derived-state → safety → temporal → referential → constraint)
- Endpoints: **55** (53 business under `/hotline` + `/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` + `/_ops/run_time_sweep` with pinned processing order)
- Errors: **31** (all triggerable; each referenced by a validation/transition and covered by a named test instance)
- Roles: **7** (Anonymous, Caller entity_backed, Counselor entity_backed, HotlineSupervisor, DataProtectionOfficer, AgencyAdmin, Analyst) — segregation-of-duties model (author≠publisher, opener≠verifier, supervisor-only de-escalation/closure/training, DPO-only purge)
- Concurrency rules: **3** OCC rules (Case.version for notes and referrals; Caller.version for consent grants), all serial-observable
- §1.8: **19 instances, all non-stub** — 2 per rule, with combinatorial_formula carrying 3 (one per mode (a) tiered branching / (b) rounding order / (c) circular dependency); every numeric assert is a precomputed literal (e.g., 75→50 score divergence, deposit exposure 190862 vs non-conformant 190861, RAW 0.2 vs DEDUP 0.25 rates)
- §1.9: **78 instances across all 9 taxonomy sections — 63 non-stub + 15 `excluded_because:` stubs** (all stubs cite existing §1.8 instance names; entities 10, state_machines 19, calculations 5+4 stubs, validations 13+2 stubs, endpoints 4+1 stub, errors 6 stubs + an audit comment mapping the remaining 25 error codes to their covering instances, rbac 7, cross-cutting 4+2 stubs, consistency 1)

**Notable design decisions:**
- **Flat topology** (per §0.3 diversity guidance) with every FK reverse-reachable; two self-referential FKs (Jurisdiction hierarchy, RightsScript supersession chain).
- **Retention/lifecycle testability fix discovered during §1.9 replay:** legal holds must be liftable after case closure, so PATCH `/hotline/cases/{id}` allows a legal_hold-only toggle on CLOSED cases while fact edits stay locked — otherwise BLOCKED_BY_HOLD → EXECUTED would be unreachable.
- **Unreachable-error fix:** ERR_JURISDICTION_CYCLE was dropped because create-only hierarchy makes cycles structurally impossible (dead error code).
- **Auto-escalation** fires from both IN_PROGRESS and PENDING_FOLLOW_UP (a missed follow-up moves the case to PENDING_FOLLOW_UP first; restricting to IN_PROGRESS would have made the path unreachable), with a no-double-escalation guard.
- **Case creation requires an ACTIVE/WRAPPED_UP session**, so every case-fixture chain legitimately exercises the full intake pipeline (script published → counselor trained → assigned → started) — this is what makes the §1.8 setup chains long but fully replayable.
- All time-dependent tests use the logical clock; no wall-clock waits anywhere; processing orders and tie-breaks use `scheduled_for`/`created_at`, never ids.

## Step 4: Generate PRD — 2026-08-14T17:04:35.221Z

All checks pass. The PRD is complete and verified. Final report:

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1783_tenant_rights_hotline_housing_counseling/workspace/PRD.md`
**Line count:** 336

### Section list
- **§1. Introduction** — 2 paragraphs (business context + system scope, `/hotline` mount)
- **§2. Global Specifications** — 11 subsections: 2.1 User & RBAC (all 7 roles with identity translations: `Caller`/`Counselor` entity-backed; `Anonymous`/`HotlineSupervisor`/`DataProtectionOfficer`/`AgencyAdmin`/`Analyst` opaque), 2.2 API Response Structure (**verbatim block, byte-identical confirmed**), 2.3 Pagination, 2.4 Common Resource Properties (incl. `CaseNote` id+`created_at`-only exception), 2.5 Logical Clock & Time Sweep (startup default 2026-08-01T00:00:00Z, pinned 4-phase sweep order), 2.6 OCC (all 3 rules, HTTP 412, no race framing), 2.7 Precision/Rounding/Units, 2.8 Nested Resource Retrieval (left-to-right), 2.9 Cascades & Compensations, 2.10 Validation Pipeline (all 12 priorities in explicit order), 2.11 Confidentiality Commitments
- **§3. Business Logic** — 9 subsections: 3.1 Reference Data (jurisdictions/counselors/interpreters/orgs), 3.2 Script Governance & Publication Chain, 3.3 Self-Help Resources, 3.4 Caller Intake & Consent, 3.5 Call Sessions & Interpreter Coordination, 3.6 Case Facts, Verification & Priority Score, 3.7 Follow-Up Cadence, Escalation & Closure, 3.8 Referrals, 3.9 Retention, Purge & Analytics
- **§4. Endpoint Definitions** — 4-column table, all **55 endpoints** (path/method/roles verified against scaffold programmatically, 0 mismatches)
- **§5. Error Code Catalogue** — 2-column table, all **31 errors** with exact HTTP statuses (verified programmatically)

### Entity coverage confirmation
All 15 entities covered (Jurisdiction, RightsScript, SelfHelpResource, Counselor, Interpreter, Caller, ConsentRecord, CallSession incl. parallel interpretation dimension, Case, CaseNote, FollowUp, LegalAidOrg, Referral, RetentionPolicy, PurgeJob); all state machines with every transition's from/to states, preconditions+error IDs, and side-effect cascades (publish 3-link cascade, consent revoke/expiry asymmetry, escalation/de-escalation compensation, slot consume/release conservation); all 12 calculations in precise prose (priority score tiers/halving/clamp, urgency thresholds, deposit exposure with pinned per-component rounding, follow-up cadence, call-volume RAW/DEDUPLICATED, 10-minute interpreter buffer, ISO-week capacity, script window invariants, 4-level retention precedence, 48h strict missed boundary, consent TTLs 7/30/90/365, queue wait); all 12 validation priorities in explicit order; all 55 endpoints; all 31 errors mentioned in §2/§3 prose; all 7 roles with exact spelling.

### Hard Contract self-check results
- **Contract 1 (Field-Name Coverage):** 108 required identifiers (entity fields + endpoint inputs + path params), 108 present, **0 missing — PASS** (2 repair passes: added `to_status`, `status`, `case_id`)
- **Contract 2 (Rule Coverage):** validations priority 12/12, OCC 3/3 (write endpoint + `expected_case_version`/`expected_caller_version` + `ERR_STALE_VERSION`/412 all named), state transitions 45/45 fully expressed, calculations 12/12, validation conditions all matchable to error IDs, endpoint side_effects/applies_to all expressed, field defaults/structured content reconstructible, sibling branches symmetric (revoke vs expiry, retire from CURRENT vs OUTDATED, RAW vs DEDUPLICATED, PROVISIONAL vs VERIFIED) — **PASS**
- **Contract 3 (§3 Path Purity):** 628 backtick tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos — **PASS**

### Consciously left coverage gaps
None. Minor note: empty-array defaults (`failed_interpreter_ids`, `declined_org_ids`, `trained_script_ids` at registration, `accessibility_needs`) are conveyed through their append/registration semantics ("starts with `trained_script_ids` empty", "defaulting to an empty list") rather than bracket literals, per the no-pseudocode rule.

## Step 5: Generate Unit Tests — 2026-08-14T17:45:21.989Z

Generation complete. Summary of what was produced for `task_1783_tenant_rights_hotline_housing_counseling`:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1783_tenant_rights_hotline_housing_counseling/`)

**test_helpers/ (Stage 1 — 1,720 lines):**
- `types.py` (385) — 16 entity TypedDicts + 18 enums; CaseNote correctly modeled `common_fields: false` (no `updated_at`/`version`)
- `api_client.py` (187) — `ApiClient(GenericApiClient)` with 45 methods, one per PRD §4 endpoint (incl. `/_clock/set_current_utc` and `/_ops/run_time_sweep`)
- `api_errors.py` (76) — all 31 PRD §5 error IDs + HTTP map, registered via `set_error_http_status_map` at import
- `assertions.py` (232) — per-entity assertions, instant-parsing comparators (so ISO formatting freedom can't cause false failures), score/tier/cadence invariant checker, analytics rate checker
- `factories.py` (124) — 10 payload factories, input fields only; anonymous-caller factory omits `phone`
- `constants.py` (70) — score/tier/SLA/TTL/buffer constants, `DEFAULT_CLOCK = 2026-08-01T00:00:00Z`, shared 75-point fact bundle
- `test_users.py` (41) — opaque-role constants (Anonymous headers deliberately omit `X-User-ID` per §2.1) + `make_caller_headers`/`make_counselor_headers` entity-backed builders
- `fixtures.py` (448) — composite scenes: `setup_hotline` (jurisdiction + author/reviewer + published script(s) + trained worker), `start_active_session`, `open_case`/`move_case_in_progress`/`verify_case`/`escalate_case`, OCC-fresh `grant_consent`/`propose_*_referral`, `setup_verified_case`, `setup_case_with_legal_aid`, `setup_retention_scene`, `setup_call_volume_scene`, sweep/clock helpers
- `__init__.py` (118) — barrel export of framework + PRD-specific names

**test_suite/ (Stage 2 — 3,274 lines):** `conftest.py` (39) + 11 test files (`test_01_intake_callers` … `test_11_analytics`).

## Test counts
- **Queue A (§1.8 Difficulty): 38 tests — all 19 instances × exactly 2 tests**
- **Queue B (§1.9 Corner): 62 tests — 62 of 63 non-stub instances × 1 test**
- Total: **100 tests**, all collected cleanly by pytest; the 15 `excluded_because:` stubs were not translated (all stub cross-references verified to resolve to real §1.8 instances).

## Instances skipped (with reason)
- `Corner/endpoints/fk_reverse_list_cases_by_caller` — **not uniquely derivable**: the PRD §4 rows say only "List … with filters" and never enumerate filter parameters, so the headline assertion (`GET /hotline/cases?caller_id=…` returns exactly that caller's cases) is not PRD-pinned. Gap left as a gap.

## Judgment calls (PRD-first adjudication, not skips)
- Timestamp assertions compare parsed instants, never raw strings (PRD §2.4 pins three-fractional-digit formatting only for `created_at`/`updated_at`).
- List-filter–dependent recipe steps were rerouted through PRD-covered reads: purge-job lookup uses the unfiltered DPO list + `caller_id` field match; script-chain singleton/consistency instances assert via GET-by-id; the pagination test relies on `limit`/`offset`/`total_count`/`has_more` (§2.3) without a filter param.
- `Corner/entities/jurisdiction_level_chain_valid` was translated on its PRD-covered half (3-level chain acceptance + field readback); the parent-filter assertion was dropped as non-derivable.
- `outcome`-echo assertion dropped from the follow-up completion test (PRD pins `completed_at` stamping, not outcome persistence on the resource).

## Self-check results
- **Stage 1:** all 9 helper modules parse and import; `test_helpers` barrel imports cleanly without `API_BASE_URL`; pyflakes clean.
- **Stage 2:** 100/100 tests collect; every test has exactly one `Design:` tag; 0 unknown tags, 0 untagged, 0 double-tagged; 0 citation failures — every ≥8-word docstring quote survives a whitespace-normalized literal grep of PRD.md (three quotes initially missed due to dropped `**bold**` markers on §2.10 numbered items; fixed). No `skip`/`skipif`/`xfail` anywhere; no "scaffold" mentions in generated code.

## Step 6: Generate Implementation — 2026-08-14T17:45:53.962Z

Done. The implementation is complete and the full benchmark suite passes: **100/100 tests** under `prd-bench-local-run --isolation per-test-server` (server restarted via `start.sh` before every test).

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1783_tenant_rights_hotline_housing_counseling/workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher (guarded pip install, `exec python3 app.py`) |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 62 | App factory, blueprint registration, envelope-wrapped error handlers (incl. 404/405) |
| `db.py` | 49 | In-memory store (dicts keyed by id) + logical clock (default 2026-08-01T00:00:00Z) |
| `errors.py` | 63 | ApiError + all 29 error-ID/HTTP-status constants |
| `middleware.py` | 39 | `X-User-Role`/`X-User-ID` auth, role admission |
| `response.py` | 52 | Envelope: `meta`/`response_type`/`data`, list pagination fields |
| `util.py` | 168 | ISO datetime/date parse/format (3-fractional-digit Z), payload/type/enum validation, limit/offset pagination |
| `serializers.py` | 243 | Exact per-entity output shapes (CaseNote: id+created_at only) |
| `services.py` | 532 | Calculations, cascades, selectors, time sweep |
| `routes_reference.py` | 328 | Jurisdictions, counselors (+training, notes audit), interpreters, orgs |
| `routes_scripts.py` | 306 | Script governance chain + self-help resources |
| `routes_callers.py` | 146 | Callers + consents + revoke |
| `routes_sessions.py` | 268 | Sessions + parallel interpretation dimension |
| `routes_cases.py` | 393 | Cases, notes (OCC), follow-ups |
| `routes_referrals.py` | 215 | Referrals, dispatch, re-route |
| `routes_privacy.py` | 166 | Retention policies, purge jobs |
| `routes_ops.py` | 110 | Clock set, time sweep, call-volume analytics |

Total 3151 lines.

## Endpoint coverage

**55/55** endpoints from the scaffold endpoint table implemented, including `POST /_clock/set_current_utc` and `POST /_ops/run_time_sweep`.

## Implementation notes

- **Storage**: pure in-memory dicts, empty at boot, zero seeding/hardcoded entities; insertion sequence numbers stabilize `created_at`-tie ordering.
- **Logical clock**: drives `created_at`/`updated_at` and every time rule; never wall-clock (wall-clock only feeds `meta.api_request_timestamp`). Clock set echoes `current_utc` verbatim.
- **State machines**: all implemented with actor restrictions (author-only submit/withdraw, reviewer-only publish/return with SoD `ERR_SCRIPT_REVIEWER_CONFLICT`, supervisor-only de-escalation/closure/retirement), terminal lockdown, and the 3-link publish cascade (supersede -> outdate resources -> cancel PROPOSED referrals `SCRIPT_OUTDATED`); retire cascade; consent revoke-vs-expire cascade asymmetry (revoke cancels DISPATCHED + releases slots, expiry cancels only PROPOSED with `CONSENT_EXPIRED`); session parallel interpretation dimension with buffered (10-min) half-open window conflict; case bubble-up, escalation (+auto follow-up +system note), de-escalation compensation; purge `BLOCKED_BY_HOLD` as a non-error transition.
- **Calculations**: priority score with pinned evaluation order and PROVISIONAL/VERIFIED variants (defective-notice halving floors, +8/escalation VERIFIED-only, clamp 0..100); urgency tiers inclusive-up; deposit exposure in integer cents via `Decimal` with per-component ROUND_HALF_UP before summation (pinned order); ISO-week org capacity computed on read (Monday 00:00Z half-open; releases automatic via status change); retention precedence chain (exact pair -> J/null -> null/C -> null/null); analytics RAW/DEDUPLICATED with 4-decimal half-up rate, zero-denominator -> 0; sweep in pinned order (consents -> follow-ups by `scheduled_for` -> referrals by `created_at` -> purge jobs by caller `created_at`) with correct boundary semantics (DUE inclusive, MISSED/consent/referral-expiry strict `>`, retention inclusive `>=`, follow-up spacing `<24h` rejects, exactly one buffer apart no conflict).
- **Validations**: pipeline order honored — auth (401) -> RBAC/ownership (403) -> SoD (403) -> path existence L-to-R (404) -> schema/unknown-field/enum rejection (400, plus 422 variants) -> OCC (`expected_case_version`/`expected_caller_version`, 412) -> state legality (409) -> verification gate -> safety gates in pinned order -> temporal -> referential -> aggregate rules. Every cascade-mutated resource gets its own `version`+1 and `updated_at` refresh.
- **Notable finding**: the follow-up-MISSED score recompute must apply the "+5 per miss" history component to the case's current stored score (per the scaffold cascade's parenthetical) rather than re-evaluating clock-sensitive fact components at the advanced sweep clock — a full re-evaluation re-tiers the eviction component as the deadline approaches and yields 100 where the suite's pinned scenario expects 75. Fixed in `services.miss_follow_up`.

## start.sh contract confirmation

Respects `$PORT` (default 10000 via `int(os.environ.get("PORT", "10000"))`), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`, and the dependency install is guarded (`if ! python3 -c "import flask"`) so per-test reboots never re-run pip. Verified with the literal evaluator invocation (`bash start.sh` from `./implementation/`) and across 100 server restarts in the suite run.

## Step 7: Run Tests and Iterate — 2026-08-14T17:50:36.601Z

All 8 parallel rounds passed cleanly — the union of failures is empty, so per the protocol I exit with the summary.

**Results across the 8-round sweep (iteration 1):**

| Round | Passed | Total |
|---|---|---|
| 1 | 100 | 100 |
| 2 | 100 | 100 |
| 3 | 100 | 100 |
| 4 | 100 | 100 |
| 5 | 100 | 100 |
| 6 | 100 | 100 |
| 7 | 100 | 100 |
| 8 | 100 | 100 |

(The background command's exit-code-1 was my post-sweep reporting one-liner hitting a `KeyError: 'nodeid'` — the results schema uses `name`/`file`/`status`. All 8 `results.{i}.json` files were written correctly and every test passed in every round.)

**Summary**

- **Iterations run:** 1 (single 8-round parallel sweep under `--isolation per-test-server`; all rounds ran to completion, no cross-round divergence).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1783_tenant_rights_hotline_housing_counseling/workspace/implementation/` is stable: 100/100 tests passing in all 8 concurrent rounds, with no flakiness signals across the sweep.

(Orchestrator verification: independently re-read all 8 `results.{i}.json` files — every round passed=100, total=100, failed=0.)

## Step 8: Finalize PRD — 2026-08-14T17:50:36.601Z

SKIPPED per the pipeline's skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline, so `PRD.md` already determined every behavior the implementation exhibits. No subagent spawned; `PRD_FINALIZED.md` intentionally absent. Step 9 will read from `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T18:00:57.509Z

All changes are in place: 32 lines revised in place, no lines added or removed. Here is the summary.

## Summary

**Source:** `workspace/PRD.md` → `workspace/PRD_COMPLETED.md` (PRD_FINALIZED.md did not exist; Step 8 was skipped).
**Line counts:** 336 → 336 (all edits are in-line inserts/revisions; no new sections or paragraphs). **Char delta:** 61,381 → 65,190 (+3,809 chars, 32 lines touched).

**Counts:** 25 ambiguity-pin changes (one covers 10 §4 table rows) + 2 mismatch-revisions.

### Ambiguity-pins
- §2.2 — insert — ambiguity — `meta.api_request_timestamp` pinned as wall-clock (logical clock governs resources/rules, never the meta envelope) — implementation/response.py:24-28, util.py:52-54
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — implementation/util.py:125-150
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by insertion order — implementation/util.py:153-158
- §2.3 — insert — ambiguity — enum-typed query filters (incl. analytics `view`) reject non-members with `ERR_INVALID_REQUEST` — implementation/util.py:161-168, routes_ops.py:44-46
- §2.5 — revise — ambiguity — clock-set response echoes the supplied `to_iso8601` verbatim as `current_utc` (not a normalized timestamp) — implementation/routes_ops.py:17-24
- §2.10 item 2 — insert — ambiguity — ownership rules that read a target's field (a consent's `caller_id` on revoke) require the target to exist first; nonexistent target → `ERR_NOT_FOUND` before ownership — implementation/routes_callers.py:129-136
- §2.10 item 5 — insert — ambiguity — any request-body entity reference (`jurisdiction_id`, `caller_id`, `opened_from_session_id`, `counselor_id`, `interpreter_id`, `script_id`, `linked_script_id`, `supersedes_script_id`, `legal_aid_org_id`, `self_help_resource_id`, …) that dangles fails as `ERR_INVALID_REQUEST` — implementation/routes_sessions.py:44-48, routes_cases.py:76-85, routes_referrals.py:76-83, routes_scripts.py:53-56
- §3.1 — insert — ambiguity — `certified_categories` members must belong to the issue-category enumeration — implementation/routes_reference.py:143-145, 199-201
- §3.1 — insert — ambiguity — counselor PATCH with `status` equal to the current status accepted as a no-op — implementation/routes_reference.py:185-189
- §3.1 — insert — ambiguity — training-certification POST responds 201 with the counselor record despite creating no new resource — implementation/routes_reference.py:229-233
- §3.1 — insert — ambiguity — `weekly_capacity` is a non-negative integer — implementation/routes_reference.py:288-290
- §3.2 — insert — ambiguity — version-monotonicity/supersession rules bind at publication, not at authoring; creation stores values as given — implementation/routes_scripts.py:41-70 vs 139-177
- §3.4 — revise — ambiguity — `is_anonymous` is a required registration field — implementation/routes_callers.py:45
- §3.5 — insert — ambiguity — `ABANDONED` stamps no `actual_end_at` (only `WRAPPED_UP`/`DROPPED` do) — implementation/routes_sessions.py:178-191
- §3.6 — insert — ambiguity — habitability duration measured in whole 24-hour days elapsed since `habitability_reported_at` (fractional days discarded), not calendar dates — implementation/services.py:143-148
- §3.6 — insert — ambiguity — a fact field explicitly set to null on case PATCH clears it — implementation/routes_cases.py:39-56, 175-176
- §3.7 — revise — ambiguity — a miss advances the stored `priority_score` by exactly +5 (clamped), re-deriving tier/cadence, without re-evaluating fact components or deposit exposure against the advanced clock — implementation/services.py:267-285
- §3.7 — insert — ambiguity — the auto-created escalation follow-up is exempt from the 24-hour spacing rule — implementation/services.py:256-264 (create_follow_up bypasses the spacing check in routes_cases.py:333-338)
- §3.7 — insert — ambiguity — "open counseling state" for note appends enumerated as `IN_PROGRESS`, `PENDING_FOLLOW_UP`, `ESCALATED` (an `OPEN` case takes no notes) — implementation/routes_cases.py:287-288, services.py:21
- §3.9 — insert — ambiguity — `retention_days` is non-negative — implementation/routes_privacy.py:47-49
- §3.9 — insert — ambiguity — executing a purge clears any prior `blocked_reason` — implementation/routes_privacy.py:162-165
- §3.9 — insert — ambiguity — analytics window bounds are optional (omitted = unbounded); `to_iso8601` earlier than `from_iso8601` → `ERR_INVALID_REQUEST` — implementation/routes_ops.py:36-41, 48-55
- §3.9 — insert — ambiguity — `do_not_aggregate` exclusion applies to session counting only; `escalated_case_count` counts cases regardless of the caller's flag — implementation/routes_ops.py:69-71 vs 87-95
- §4 — revise — ambiguity — named the exact filter query parameters on all 10 list-endpoint rows (jurisdictions, scripts, resources, consents, sessions, cases, follow-ups, referrals, retention-policies, purge-jobs) — implementation/routes_reference.py:111-122, routes_scripts.py:82-105 & 250-264, routes_callers.py:110-126, routes_sessions.py:81-104, routes_cases.py:129-155 & 346-357, routes_referrals.py:124-141, routes_privacy.py:78-92 & 108-119
- §5 — insert — ambiguity — failures that never reach an operation share the error envelope: unmatched path → `ERR_NOT_FOUND` (404); wrong method/malformed body/unexpected failure → `ERR_INVALID_REQUEST` carrying the transport status (405/400/500) — implementation/app.py:40-54

### Mismatch-revisions
- §2.7 — revise — mismatch — replaced "minute granularity" (interpreter windows) / "second granularity" (consent/follow-up TTL) with comparison at the exact precision of the supplied ISO 8601 timestamps, matching impl's exact datetime comparisons — implementation/services.py:369-385, 471-489; util.py:25-39
- §3.1 — revise — mismatch — scoped `ERR_JURISDICTION_LEVEL_MISMATCH` (422) to level/parent-level inconsistency only; a `COUNTY`/`CITY` created without `parent_jurisdiction_id`, naming a nonexistent parent, or reusing a `code` fails as `ERR_INVALID_REQUEST` (400) — implementation/routes_reference.py:60-85

No other divergences found: all endpoint role lists, state machines, cascades, scoring/exposure formulas, SLA/capacity rules, sweep order and counters, error catalogue, and response field shapes already match `implementation/` uniquely.
