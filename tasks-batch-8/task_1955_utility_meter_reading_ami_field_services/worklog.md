# Worklog — task_1955_utility_meter_reading_ami_field_services

Scenario: 1955. Utility Meter Reading & AMI Field Services (utility metering contractor): route assignment & handheld/AMI read collection, no-read/estimate rules & re-read dispatch, meter exchange work order & serial swap, tamper/theft indication & investigation, read window & billing cycle alignment, field-safety hazard (dog/access) flag, backlog & meter-reading accuracy SLA, endpoint failure & replacement program

Target difficulty: harder than expert level.

## Step 1: Create task directory — 2026-08-15T00:00:00.000Z

Directory tasks/task_1955_utility_meter_reading_ami_field_services/ and workspace/ pre-created by pipeline driver (index 1955 assigned by scenario ID, not by scanning).

## Step 2: Generate scaffold — 2026-08-15T03:41:00.000Z

All three artifacts are complete and pass the linter. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/SCAFFOLD.yaml` (~102 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (~78 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/SCAFFOLD_CORNER_DESIGN.yaml` (~210 KB)

The pre-existing `worklog.md`/`workspace/` in that directory were not touched. No sibling `tasks/task_*` content was read — only the scaffold-generator skill's own SKILL.md, claim-extraction guide, lint script, and example format references.

## SCAFFOLD.yaml counts (§1.0–§1.7)

- **Entities: 13** — FieldTechnician, ServiceAccount, Meter (three parallel state dimensions: lifecycle × AMI comms × tamper), BillingCyclePeriod, Route, RouteStop, MeterRead (self-referential via `supersedes_read_id`), HazardFlag, WorkOrder, Investigation, ReplacementCampaign, CampaignEnrollment, OpsSnapshot
- **State machines: 15** (63 transitions) — cyclic loops on Route (assign/unassign/reassign), WorkOrder (REWORK), Investigation (evidence/disposition revision loop); parallel dims on Meter
- **Concurrency rules: 3** (all true OCC races per §1.2.1 filter): route-reassign, stop-read-supersede, work-order-reschedule — each with `expected_*_version` and 412 ERR_STALE_VERSION
- **Calculations: 9** — estimate_read_value (dual variant), route_read_rate (GROSS/NET dual variant), no_read_escalation_score (weighted, mode a), theft_backbill_amount (nested rounding, mode b), sla_read_rate_evaluation (integer cross-multiplication `covered*200 < eligible*197`, mode c ordering), read_window_alignment, hazard_ttl_expiry, endpoint_comms_degradation, backlog_aging_buckets
- **Validations: 27** ordered priorities (auth → ownership → existence → OCC → state → safety → temporal → constraint → referential → quota → aggregate → closure), with intra-row check order pinned where multiple errors share a priority
- **Endpoints: 81** (flat topology, `api_prefix: ""`, all collections rooted at `/`; includes `POST /_clock/set_current_utc` with mandated default `2026-08-01T00:00:00Z`)
- **Errors: 45** — every one referenced by a validation/transition and exercised by a named design instance
- **Roles: 5** — MeterOpsAdmin/Dispatcher/BillingLiaison/Investigator (opaque), FieldTechnician (`entity_backed:FieldTechnician`); segregation-of-duties on investigation close (closer ≠ opener, 403 ERR_SEGREGATION_OF_DUTIES)

## §1.8 difficulty design — 18 instances (9 rules × 2)

All numeric asserts pre-computed and verified in Python: estimate variants 10270 vs 10310 on identical history; GROSS 50.00 vs NET 66.67; escalation score 60 (creates RE_READ WO) vs 35 (none) on a streak-1/streak-0 contrast; backbill 14048 cents (per-month rounding) vs naive 14049; Meter parallel-dim independence; investigation revision loop with version == 6; two depth-3 cascades (exchange→enrollment-withdrawal→WO-cancel→campaign-auto-COMPLETED; tamper-read→investigation+SUSPECTED→enrollment-withdrawal with campaign staying OPEN); priority conflicts state>constraint and safety>temporal; boundary pins on read-window dates (inclusive both ends) and estimate cap (streak 2 allowed, 3 rejected); cross-entity gates (Stop×Route, Period×Stop); overlap rules with *different interval semantics* (half-open shift windows reject/adjacency-allow vs hazard-flag interval-merge); compensating invariants on technician commitment slots and route stop-partition cardinality.

## §1.9 corner design — 101 instances (96 active, 5 excluded stubs)

Nine guide-matched sections: entities (16), state_machines (13), calculations (12 incl. 4 stubs), validations (35), endpoints (5), errors (1), rbac (6), complexity_layers (6 incl. 1 stub + 3 OCC stale-version tests), consistency_model (1). Covers every entity creation/defaults/computed field, terminal lockdowns for all terminal states, both legs of the hazard-clear conditional cascade, quota exact-fit/overflow/atomicity, SoD two-leg, AMI miss 2-vs-3 and 13-vs-14-day FAILED boundaries, strict hazard-expiry inequality, SLA both legs, sweep-order observability (hazard expiry before escalation), pagination/filter interaction, and the pinned default clock.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(81 endpoints, 13 entities, 18 §1.8 + 96 active §1.9 instances, 1254 calls scanned.)

## Notable harder-than-expert design decisions

- **Flat topology + `api_prefix: ""`** — chosen because lint check (f) only resolves 2-segment paths under the prefix; also §0.3 prioritizes flat (0% of examples).
- **True-race discipline**: reassign-in-progress and exchange-vs-pending-read were classified as state preconditions (ERR_ROUTE_NOT_REASSIGNABLE / ERR_METER_NOT_INSTALLED_AT_ACCOUNT), with an explicit corner instance documenting that distinction; only the three genuine supersede races got OCC.
- **AMI dual-path reads**: head-end ingestion auto-validates while field captures stay PROVISIONAL — this is what makes estimate-history fixtures executable without test-only seed endpoints.
- **Validation ordering fixes made during design**: stop-actionability (P8) deliberately precedes the generic state gate (P9), and ownership (P4) precedes state, which forced one corner instance to be redesigned (assign-from-ASSIGNED instead of start-from-DRAFT, since ownership on a null technician would mask the state error).
- **One replay bug caught and fixed pre-lint**: an OCC-priority corner fixture originally left the AMI meter COMMUNICATING (read present in snapshot window), which would have produced zero route stops; a second snapshot was inserted to force DEGRADED eligibility.

## Step 3: Copy shared files — 2026-08-15T03:42:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1955_utility_meter_reading_ami_field_services/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T03:55:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/workspace/PRD.md` — 394 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context + system-goals angle)
- §2 Global Specifications: 2.1 Roles/RBAC (5 roles, entity-backed vs opaque `X-User-ID` semantics per role), 2.2 API Response Structure (emitted **byte-identical** to `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 Logical Clock (default `2026-08-01T00:00:00Z`, never wall-clock), 2.5 Common Resource Properties, 2.6 Validation Discipline & Evaluation Order (full 27-rung ladder), 2.7 OCC (3 rules), 2.8 Billing Calendar/Read Windows/Shift Windows, 2.9 Register Integrity & Precision, 2.10 Field Safety, 2.11 Read-Rate Accounting & 98.50% SLA, 2.12 Cascading State Consistency
- §3 Business Logic (9 subsections): 3.1 Master Data, 3.2 Periods & Route Planning, 3.3 Route Execution & Capture, 3.4 Validation/Estimation/Billing Finalization, 3.5 Hazard Flags, 3.6 Investigations, 3.7 Work Orders, 3.8 Replacement Campaigns, 3.9 Ops Checkpoints & SLA
- §4 Endpoint table (81 rows, 4 columns) + status-code paragraph; §5 Error catalogue (45 rows, 2 columns)

**Coverage audit (all three Hard Contracts PASS, verified mechanically against the scaffold):**

```
Field coverage check:
- entities[].fields: 106 required, 106 present, 0 missing
- endpoints[].request_body/input: 80 required, 80 present, 0 missing
- endpoints[].query_params: 49 required, 49 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose (§2.6 ordered ladder incl. pinned intra-row orders: quota→eligibility→already-enrolled; unresolved-stops→missing-billable-read; stop-actionability before the generic state gate), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_route_version / expected_route_stop_version / expected_work_order_version + ERR_STALE_VERSION 412 all named in §2.7; §3 references them path-free), 0 missing
- state_machines[].transitions: 63 checked (15 machines), 63 fully expressed (4 pairs — SUSPENDED→CLOSED, WINDOW_CLOSED→BILLED, COMPLETED→RECONCILED, {CONFIRMED_THEFT,CLEARED}→CLOSED — flagged by a same-sentence heuristic but confirmed present at paragraph level), 0 missing
- calculations[]: 9 checked, 9 fully expressed with constants embedded as words (30-day TTL, 14-day failure, 3-miss threshold, 7-day aging, 365-day history, cap 3, min 2, ESC 10/25/5/7/15/40/100, 11.25 cents, 25% penalty, 197/200 integer cross-multiplication, 2dp half-up rates), 0 missing
- validations[] conditions: 45 error IDs checked, 45 matchable to triggers in §2/§3 narrative (0 missing); §5 table complete
- endpoints[].side_effects / applies_to: 81 checked, 81 expressed (all cascades rendered: suspend→stop cancel, exchange serial swap, tamper enrollment withdrawal, campaign close/auto-complete, hazard revert, window-close sweep, snapshot 4-step pinned sweep), 0 missing
- entities[].fields[] structured content: 106 checked, 106 reconstructible (types, defaults, initial values, enum memberships, null-when semantics all in prose), 0 missing
- sibling-branch symmetry: 4 groups checked (4 work-order completion payloads, 2 estimate variants, hazard merge vs renew, withdrawal-cascade sources), 4 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 796
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Rules I could not render verbatim and how I handled them:**

1. **Worked-fixture numbers embedded in the scaffold's `calculations[].variants` and formula comments** (estimate variants "result 10270 / 10310 for the canonical fixture"; backbill "[333,333,333] → 3746 each / 11238 / 2810 / 14048 vs naive 14049"). These are design-index-style expected values, not rules. I omitted the fixture outcomes entirely but rendered the formulas losslessly, including the load-bearing distinctions the fixtures illustrate: per-month rounding pinned *before* summation ("summing first and rounding once produces a different result and is rejected") and the SPLY→TRAILING_AVERAGE pinned fallback made observable on the created read's `estimation_method`.
2. **ServiceAccount close discrepancy inside the scaffold itself**: the state machine marks `SUSPENDED→CLOSED` "not exposed; no endpoint in v1" while the endpoint table exposes close (`{ACTIVE,SUSPENDED}→CLOSED`, `ERR_ACCOUNT_HAS_OPEN_WORK`) and validation 22 defines its gate. I followed the endpoint table + validation (authoritative for §4) and rendered close as permitted from either `ACTIVE` or `SUSPENDED` with the open-work gate — no invented behavior, both scaffold sources honored where they agree.
3. **`backlog_count` definitional nuance**: entity field and sweep step 4 say "stops in {PENDING, NO_READ_PENDING} on non-CANCELLED routes" while the finalize formula says "eligible stops in {PENDING, NO_READ_PENDING}". I rendered each phrasing in its own trigger context (snapshot creation vs. finalize evaluation) rather than inventing a reconciliation.

The forbidden design-index files were never opened. No sibling task directories were read.

## Step 6: Generate implementation — 2026-08-15T04:22:00.000Z

Implementation complete and verified. Final summary:

## File inventory

All under `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/workspace/implementation/`:

- `start.sh` — guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground
- `requirements.txt` — `flask>=2.0`
- `app.py` — Flask entry point (0.0.0.0:$PORT, default 10000, threaded), global RLock around requests, ApiError/404/405/exception handlers producing the envelope
- `db.py` — empty-at-boot in-memory store (13 dicts), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), `stamp_new`/`touch` (version starts 1, every mutation bumps `version` + `updated_at`)
- `errors.py` — all 42 error IDs from the catalog
- `util.py` — ISO8601/strict `YYYY-MM-DD` parsing, 3-fractional-digit formatting, half-up Decimal/Fraction rounding, 2dp rate helper, shift-interval overlap
- `response.py` — envelope (`meta.api_request_id` `req_…`, `api_request_timestamp`, `response_type`, `data`), error body, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp [1,100]/≥0)
- `middleware.py` — `X-User-ID`/`X-User-Role` validation, role gating, typed body-field extractors
- `serializers.py` — per-entity serializers with on-the-fly computed fields (`current_meter_id`, `last_validated_*`, `unresolved_stop_count`, route counters, campaign counts, `is_billable`)
- `services/cascades.py` — account-suspend stop cancellation, meter-suspect/removed enrollment withdrawal (per-trigger cancel-state filters), campaign auto-complete, hazard-resolution stop revert, technician window-conflict scan, evidence-hold check, read factory (streak reset on auto-VALIDATED)
- `services/estimates.py` — `estimate_read_value` both variants with pinned SPILY→TRAILING fallback, Fraction-precision average, single final half-up rounding
- `services/snapshot.py` — pinned 4-step sweep (hazard expiry strict `<`; AMI comms DEGRADED→NON_COMMUNICATING@3→FAILED@14d inclusive; escalation score cap 100 / threshold 40 with auto RE_READ orders; aggregates + 7-day inclusive aging) and integer cross-multiplication SLA verdict
- `routes/` — 13 blueprints: `clock`, `technicians`, `accounts`, `meters` (install/retire/ami-reads), `periods` (window gates, finalize gates in pinned order), `routes` (stop auto-generation, OCC reassign, reconcile GROSS/NET), `stops` (capture with supersede/tamper cascades, mark-no-read, skip-hazard, estimate), `reads` (validate/reject cascades), `hazards` (merge-on-repeat returning 200, renew, clear), `workorders` (typed completion cascades: RE_READ/EXCHANGE serial swap/TAMPER_CHECK/ENDPOINT_SWAP), `investigations` (backbill per-month rounding pinned, SoD + verified-exchange close gates), `campaigns` (atomic batch enroll quota→eligibility→duplicate, close cascade), `snapshots`

## Boot sanity check

`bash start.sh` from a fresh process boots in ~1s and answers requests correctly (verified repeatedly, including after final edits): created resources stamp the default logical clock `2026-08-01T00:00:00.000Z`, success/error envelopes match §2.2 exactly, and seven custom end-to-end suites pass — covering read capture/supersede/validate/reject, estimate math (verified 2200 trailing-average and 980 SPILY values, fallback observability, streak cap), AMI comms sweep through FAILED with the 14-day inclusive boundary, campaign enroll/swap/auto-complete/close/withdrawal cascades, tamper investigations with canonical `[333,333,333] → backbill_cents 14048`, hazard merge/renew/clear/strict-expiry/revert, SLA breach boundary semantics, window conflicts (AM+PM adjacency allowed), OCC 412s on all three guarded writes, and finalize-billing gate ordering.

## PRD ambiguities resolved (chosen interpretation)

1. **`supersedes_read_id` direction** — PRD §3.3 prose ("the prior read… with its supersedes_read_id pointing at the new read") contradicts the scaffold field description ("the read this read replaces"). Followed PRD prose: the superseded (old) read's `supersedes_read_id` points at the new read.
2. **Work-order reschedule state** — scaffold transition says `to: OPEN` but its own trigger/note say "state unchanged… self-loop"; implemented as a true self-loop (status unchanged; only schedule + version change), including for DISPATCHED orders.
3. **MeterOpsAdmin capture** — scaffold actor note "MeterOpsAdmin (correction=true only)" enforced symmetrically: admin capture without `correction=true` → `ERR_FORBIDDEN_FOR_ROLE` (403).
4. **Estimate read `read_at`** — unspecified; set to the period's `read_window_close_date` at `T00:00:00.000Z` ("the estimate targets the window close").
5. **Trailing-365-day history gate anchor** — anchored to the logical clock (`now - 365d <= read_at <= now`).
6. **Auto-created EXCHANGE order at confirm-theft** — no schedule is specified; created with `scheduled_date`/`work_shift` null (null schedule never conflicts).
7. **"Open work" for account close** — stops in PENDING/READ_CAPTURED/NO_READ_PENDING/SKIPPED_HAZARD, orders in OPEN/DISPATCHED/IN_PROGRESS/COMPLETED/REWORK, any non-CLOSED investigation.
8. **Technician conflict commitment set** — routes in ASSIGNED/IN_PROGRESS and orders in DISPATCHED/IN_PROGRESS (mirrors the deactivate definition of open commitments).
9. **"Previous snapshot" for the AMI window** — greatest existing `snapshot_at` strictly earlier than this one; first-snapshot window is `(meter.created_at, snapshot_at]`.
10. **Route stop generation eligibility** — per scaffold's "of the period's cycle" phrase, restricted to accounts whose `billing_cycle_code` equals the period's cycle code (PRD lists only the ACTIVE/meter/comms conditions).
11. **Day-count arithmetic** — all day differences (estimate horizons, escalation urgency, aging) use date-part subtraction per the PRD's date-granularity convention.
12. **Pagination params out of range** — clamped (limit to [1,100], offset to ≥0); non-numeric values → `ERR_INVALID_REQUEST` 400.
13. **Clear on non-ACTIVE hazard flag** — `ERR_HAZARD_FLAG_NOT_ACTIVE` is catalogued "(renew only)", so clear on EXPIRED/CLEARED → generic `ERR_INVALID_STATE_TRANSITION`.

One masked-failure bug was found and fixed during verification: a missing `fmt_dt` import in the snapshot sweep left a partial mutation (meter NON_COMMUNICATING without `non_communicating_since`) — import added, full suite re-verified clean, pyflakes passes with zero warnings.

## Step 5: Generate unit tests — 2026-08-15T04:41:00.000Z

Generation complete. Final summary:

## Counts

**Queue A (Difficulty): 36 tests** — 18 instances × 2 tests each, all instances covered, none skipped.
**Queue B (Corner): 95 tests** — 96 non-stub instances, 1 skipped (below); the 5 `excluded_because:` stubs were not translated (all cross-references verified to resolve to real difficulty instances: `estimate_variant_values_pinned`, `route_reconcile_gross_net_rates`, `escalation_streak_contrast`, `backbill_rounding_order`, `cascade_chain_exchange_full_depth`).
**Total: 131 tests** across 12 files; `pytest --collect-only` collects all 131 cleanly.

## Skip list (1 instance)

- `Corner/entities/entity_meter_system_field_input_ignored` — PRD §3.1 pins that a new meter "starts with meter_status IN_STOCK" but never states how create endpoints treat a client-supplied `meter_status` field (ignore vs. reject); two faithful PRD readers could ship different behavior, so the asserted "input ignored" outcome fails unique derivability.

## Adjudication note (not a skip)

Three instances (`occ_stop_read_capture_stale_version`, `actual_read_supersedes_estimate_and_compensates_streak`, `correction_capture_requires_admin_and_supersedes_provisional`) assert `new_read.supersedes_read_id == old_read_id`, but PRD §3.3 prose states the opposite direction ("transitions the prior provisional current read to SUPERSEDED with its supersedes_read_id pointing at the new read"). The direction is not uniquely derivable (prose vs. field-name semantics diverge), so those tests assert the supersede facts both readings agree on — old read `SUPERSEDED`, `is_billable` false, new read `PROVISIONAL`, stop `current_read_id` updated, streak compensation — and do not hard-code pointer direction. Core claims (OCC 412, streak 1→0, admin-only correction) are fully asserted.

## test_helpers inventory (9 files)

- `types.py` — 13 entity TypedDicts (all carry the common quartet), 21 status/type enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (81 endpoints incl. `/_clock/set_current_utc`); module-level `api_client` singleton
- `api_errors.py` — `ApiErrorId` (all 45 error IDs from PRD §5) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (13), `assert_iso_instant_equal` (instant-pinned, serialization-tolerant timestamp comparison), campaign/route counter invariants
- `factories.py` — payload factories for every creatable resource + capture/reschedule/rework/confirm-theft/enroll payloads, unique account/serial generators
- `constants.py` — PRD thresholds (HAZARD_TTL_DAYS=30, AMI_MISS_THRESHOLD=3, ENDPOINT_FAILURE_DAYS=14, estimate caps, escalation weights, SLA 197/200, RATE 11.25, PENALTY 0.25, BACKLOG_AGED_DAYS=7, pagination, UNKNOWN_UUID)
- `test_users.py` — `TEST_USERS` shared constants for all 5 roles + per-instance `make_*_headers` builders (mandatory `make_field_technician_headers(entity_id)` for the entity-backed role)
- `fixtures.py` — ~40 helpers across all 5 tiers: single-call happy-path wrappers, `setup_account_with_installed_meter`, `setup_in_progress_route`, `setup_no_read_pending_stop`, `setup_ami_account_with_history`, `drive_ami_meter_comms`/`fail_ami_meter`, `setup_failed_meter_in_open_campaign`, investigation advancement, entity getters
- `__init__.py` — barrel export (framework generics + PRD-specific)

## Stage 2 self-check result

Scripted audit (then removed as a working artifact): **131 tests found, 131 tagged, 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances, 0 tags pointing at stubs, 0 broken stub cross-references.** Coverage: every difficulty instance has exactly 2 tests; every non-stub corner instance has ≥1 (only the sanctioned skip above has 0). Citation pass: every double-quoted PRD citation in every docstring was grep-verified verbatim against `workspace/PRD.md` (one semicolon/period mismatch found and fixed during the sweep). No `pytest.mark.skip`/`skipif`/`xfail` anywhere.

## Step 7: Run tests and iterate — 2026-08-15T05:05:00.000Z

All 8 rounds pass 131/131 with zero failures and zero errors. The loop is complete. (Orchestrator verification: all 8 results.{1..8}.json files independently read — 131/131, 0 failed, 0 errors in every round.)

## Summary

**Iterations run:** 2 eight-round sweeps.
- Sweep 1: 124/131 in every round — 7 deterministic failures (identical across all 8 rounds; the "flaky" appearance in the interleaved console stream was an artifact of 8 pytest processes sharing one output file — JUnit results were identical per round).
- Sweep 2 (after fixes): **131/131 passed in all 8 rounds**, union of non-passing tests empty.

**Tests deleted:** None. Every failing assertion traced to verbatim PRD prose; no PRD-silence or unique-derivability collapses found.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/test_helpers/fixtures.py` — `setup_failed_meter_in_open_campaign`: typo `enrollment = enrollment[0]` → `enrollments[0]`. The UnboundLocalError crashed 4 campaign tests (`test_campaign_auto_completes_when_last_enrollment_replaced`, `test_campaign_close_withdraws_enrollment_and_cancels_order`, `test_enrollment_duplicate_across_open_campaigns_rejected`, `test_enrollment_list_reverse_reachable_from_campaign`) in setup before any assertion — matching the triage hint that ≥5 failures sharing a setup trace means one upstream fixture bug.

**Fixes applied to `test_suite/`:**
- `test_02_routes_lifecycle.py` — `_assigned_route_with_stop` discarded the `assign` 200 response and returned the stale creation-time route object, so `test_capture_rejected_while_route_assigned` asserted `route_status == "ASSIGNED"` against `DRAFT`. Now captures the assign response (PRD §2.2: modify operations return the updated resource).
- `test_06_hazards.py` — `test_hazard_clear_reverts_skipped_stop_and_second_flag_blocks_revert`: the scenario cleared the *cited* DOG flag while ACCESS was still ACTIVE (no revert — correct), then expected clearing the *uncited* ACCESS flag to release the DOG-citing stop. PRD §3.5 ("every stop … citing this flag reverts") and §3.3 ("when the cited flag is cleared or expires") pin the revert trigger to the cited flag's own resolution, so the PRD determines no revert there. Reordered the clears: clear the uncited flag first (stop stays SKIPPED_HAZARD — the "no other ACTIVE hazard flag remains" gate fails), then clear the cited flag (reverts to PENDING, `hazard_flag_id` null). Both legs now map exactly onto the PRD sentence; assertions unchanged.
- `test_07_work_orders.py` — added missing `get_campaign` import (NameError in `test_exchange_completion_cascades_to_campaign_completion`).

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful in every failing path — all 7 failures were test-artifact bugs (1 fixture typo, 1 stale-object assertion, 1 scenario wired contrary to the PRD-pinned cascade trigger, 1 missing import).

## Step 8: Finalize PRD — 2026-08-15T05:12:00.000Z

Task complete. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/workspace/PRD_FINALIZED.md` — byte-identical to `PRD.md` (verified with `diff -q`).

## Summary

**Line counts / %-delta:** PRD.md = 393 lines, PRD_FINALIZED.md = 393 lines, 0% delta. Zero edits.

**Changes:** None. All four `<step_7_diff>` items verified against `implementation/` and concluded to be pure test-artifact bugs on behavior the PRD already pins uniquely.

**Per-item verification log (no edit committed for any item):**

1. **`test_helpers/fixtures.py` — `enrollment = enrollment[0]` → `enrollments[0]` typo.**
   Pure test bug. Subject check: batch-enroll response shape. PRD §3.8 already pins "A successful batch returns 201 with the created enrollments" (plural array), confirmed by `implementation/routes/campaigns.py:69` (`enroll` builds and returns the enrollments array at 201). PRD uniquely determines the behavior the fixed fixture relies on; no silence.

2. **`test_02_routes_lifecycle.py` — `_assigned_route_with_stop` discarded the assign 200 response.**
   Pure test bug. Subject check: modify-operation response body. Enumerated impl paths: `implementation/routes/routes.py:148-161` (`assign` returns `success(ser_route(route), 200)` after mutating to `ASSIGNED`), plus the parallel modify endpoints `reassign` (line 181), `unassign` (line 193), `start` (line 214), `complete` — all return the updated resource at 200. PRD §2.2 ("operations that create or modify a resource will return the created or updated resource object in the data field") and §4 ("Operations that modify an existing resource return `200 OK`") already pin this universally. PRD already determines it.

3. **`test_06_hazards.py` — clear ordering rewired (uncited flag first, cited flag second).**
   Old scenario contradicted pinned PRD prose; test fix, not PRD silence. Subject check: hazard-skip revert trigger. Enumerated impl paths: `implementation/services/cascades.py:53-76` (`hazard_resolution_cascade`: returns early if any other ACTIVE flag remains on the account; reverts only `SKIPPED_HAZARD` stops whose `hazard_flag_id == resolved_flag_id`; only when route is `ASSIGNED`/`IN_PROGRESS`), and both call sites — manual clear `implementation/routes/hazards.py:97` and snapshot expiry `implementation/services/snapshot.py:47`. PRD §3.5 ("When a flag clears or expires and no other ACTIVE hazard flag remains on the account, every stop … citing this flag reverts to PENDING … provided the stop's route is ASSIGNED or IN_PROGRESS") and §3.3 ("when the cited flag is cleared or expires") describe exactly this, covering both trigger paths. PRD already pins it; the reordered test now maps onto the PRD sentence.

4. **`test_07_work_orders.py` — missing `get_campaign` import.**
   Pure test bug (NameError); no behavioral content, no PRD implication.

No implementation fixes and no test deletions occurred in Step 7, and every failing path traced to verbatim PRD prose that the implementation already follows, so the correct finalized PRD is the unchanged one.

## Step 9: Complete PRD — 2026-08-15T05:25:00.000Z

All 23 edits landed (22 diff hunks; line 202 holds two distinct changes). Final verification stats are in. Here is the summary.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1955_utility_meter_reading_ami_field_services/workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md 393 lines / 73,106 chars → PRD_COMPLETED.md 393 lines / 76,661 chars (char-delta **+3,555**; all changes in-paragraph, no sections added).

**Counts:** 19 ambiguity-pins, 5 mismatch-revisions (24 changes total).

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped into [1,100] / up to 0; non-integer values → `ERR_INVALID_REQUEST` 400 — implementation/response.py:37-58
- §2.3 — insert — ambiguity — list-order ties on identical `created_at` retain creation (insertion) order — implementation/response.py:75-77
- §2.3 — insert — ambiguity — `total_count` = full filtered size; `has_more` ⇔ `offset` + returned < `total_count` — implementation/response.py:59-66
- §2.8 — insert — ambiguity — technician commitment set for window conflicts = routes in `ASSIGNED`/`IN_PROGRESS` + work orders in `DISPATCHED`/`IN_PROGRESS` — implementation/services/cascades.py:79-106
- §3.1 — insert — ambiguity — account-close "open work" pinned: stops in `PENDING`/`READ_CAPTURED`/`NO_READ_PENDING`/`SKIPPED_HAZARD`, orders in `OPEN`/`DISPATCHED`/`IN_PROGRESS`/`COMPLETED`/`REWORK`, investigations in any state ≠ `CLOSED` (incl. `CLEARED`/`CONFIRMED_THEFT`) — implementation/routes/accounts.py:17-19,118-129
- §3.2 — revise — mismatch — stop auto-generation restricted to accounts whose `billing_cycle_code` equals the period's `cycle_code` (PRD prose admitted any account) — implementation/routes/routes.py:91-93
- §3.3 — revise — mismatch — assign/reassign conflict set revised from "another assigned route or dispatched work order" to routes `ASSIGNED`/`IN_PROGRESS` + orders `DISPATCHED`/`IN_PROGRESS` — implementation/services/cascades.py:85-105
- §3.3 — insert — ambiguity — `MeterOpsAdmin` may capture only with `correction=true`; admin capture without it → `ERR_FORBIDDEN_FOR_ROLE` 403 — implementation/routes/stops.py:63-68
- §3.4 — insert — ambiguity — AMI ingestion on a non-`IN_SERVICE` meter fails `ERR_INVALID_STATE_TRANSITION` 409; no read-window containment check applies to ingestion — implementation/routes/meters.py:114-115
- §3.4 — revise — mismatch — removed the claim that validation cascades the stop from `VALIDATED`/`ESTIMATED` to `SUPERSEDED`; impl's only validation-time stop move is `READ_CAPTURED`→`VALIDATED` — implementation/routes/reads.py:60-64
- §3.4 — insert — ambiguity — trailing-365-day history window anchored to the logical clock's current instant, both endpoints inclusive — implementation/services/estimates.py:20-26 + implementation/routes/stops.py:272
- §3.4 — insert — ambiguity — estimation day counts are calendar date-part subtractions; `read_at` ties broken by creation order; degenerate cases (no strictly-earlier read, or same calendar date) yield the latest validated value — implementation/services/estimates.py:29-59 + implementation/util.py:42-46
- §3.4 — insert — ambiguity — estimate read stamped `read_at` = `read_window_close_date` at `T00:00:00.000Z`; `meter_id` = account's currently installed meter (null when none) — implementation/routes/stops.py:279-288
- §3.5 — insert — ambiguity — repeat-report merge also re-stamps `reported_at` to the new instant and leaves `reported_by_technician_id` unchanged — implementation/routes/hazards.py:50-55
- §3.5 — insert — ambiguity — clearing a non-`ACTIVE` flag → `ERR_INVALID_STATE_TRANSITION` 409; `ERR_HAZARD_FLAG_NOT_ACTIVE` is renew-only — implementation/routes/hazards.py:93-94 vs 105-106
- §3.6 — revise — mismatch — tamper-indication auto-open condition is per-meter only (not "account and meter"), and the auto-created investigation gets `indication_type` `TAMPER_FLAG` — implementation/routes/stops.py:174-193 + implementation/services/cascades.py:109-113
- §3.6 — insert — ambiguity — confirm-theft auto-created `EXCHANGE` order carries `investigation_id` and is born with null `scheduled_date`/`work_shift` — implementation/routes/investigations.py:175-197
- §3.7 — insert — ambiguity — `TAMPER_CHECK` creation against a `CLOSED` investigation → `ERR_INVALID_STATE_TRANSITION` 409 — implementation/routes/workorders.py:77-82
- §3.7 — revise — mismatch — reschedule is a true self-loop: order remains in its current status (a `DISPATCHED` order stays `DISPATCHED`), technician assignment retained — implementation/routes/workorders.py:183-201
- §3.7 — insert — ambiguity — `RE_READ` completion read is attributed to the account's currently installed meter (null when none) — implementation/routes/workorders.py:234-243
- §3.7 — insert — ambiguity — exchange rollback screen applies to `old_final_read_value` only (`new_initial_read_value` unscreened); both exchange reads stamped `read_at` = completion instant from the logical clock — implementation/routes/workorders.py:257-291
- §3.7 — insert — ambiguity — `rework_reason` is mandatory; missing → `ERR_INVALID_REQUEST` 400 — implementation/routes/workorders.py:391-392
- §3.8 — insert — ambiguity — `meter_ids` must be a non-empty array (else 400); duplicate check = enrollment in `ENROLLED`/`WORK_ORDER_CREATED` under a still-`OPEN` campaign, or a meter id repeated within the batch — implementation/routes/campaigns.py:72-126
- §3.9 — insert — ambiguity — "previous snapshot" = the existing OpsSnapshot with the greatest `snapshot_at` strictly earlier than this one's — implementation/services/snapshot.py:29-35

**Verification:** `diff` shows exactly 22 hunks, all single-paragraph inline edits; no new sections, no behavior invented beyond what the implementation exhibits.

## Pipeline complete — 2026-08-15T05:25:00.000Z

All 9 steps done. Final state: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml (harder-than-expert: 13 entities, 15 state machines, 9 calculations, 27 validation priorities, 81 endpoints, 45 errors, 3 OCC rules; 18 difficulty + 96 active corner instances); PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (24 pins); 131 tests (36 difficulty + 95 corner, 1 sanctioned skip), 8/8 stability rounds at 131/131 under per-test-server isolation.
