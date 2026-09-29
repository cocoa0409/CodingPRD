# Worklog — task_2312_consumer_affairs_product_quality_contact

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2312_consumer_affairs_product_quality_contact/` and `tasks/task_2312_consumer_affairs_product_quality_contact/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T00:00:00.000Z

Scaffold complete at `/home/auto/…` — precisely: `/home/ubuntu/github/CodingPRD/tasks/task_2312_consumer_affairs_product_quality_contact/`

**Files (all three, as specified)**
- `SCAFFOLD.yaml` — §1.0–§1.7 only, no design keys present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Seed-table counts (§1.1–§1.7)**
15 entities · 10 state machines · 2 concurrency rules (OCC) · 10 calculations · 45 ordered validations · 79 endpoints · 57 error codes · 6 roles (3 segregation-of-duties pairs).
Entities: StaffUser, Consumer, Plant, ProductionLine, Product, ProductionLot, Contact, Complaint, SampleKit, CustodyEvent (immutable), Remedy, RegulatoryReport, TrendSignal, SignalMembership (immutable junction), ResponseTemplate.
Complexity profile: `difficulty: expert_plus`, topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation]`.

**Difficulty design (§1.8)** — 21 instances over all 9 rules (2/3/2/2/3/3/2/2/2). Highlights: provisional-vs-adjudicated severity band flip driven by the regulated-food multiplier; sequential-vs-fused rounding pinned to a one-cent difference (111.89 vs 111.88); goodwill uplift rate keyed on base not payout; a conjunctive trend gate where a 50 ppm lot fires nothing and a 30 ppm lot fires; a depth-4 recall cascade whose far end is a refused `POST /production-lots`; three priority-conflict pairs 27/16/4 levels apart; the S1 band boundary at exactly 90.00; a zero-denominator sentinel; half-open trend windows vs closed kit-occupancy intervals (opposite endpoint conventions); and two conservation invariants (money and counts) across full round trips.

**Corner design (§1.9)** — 89 instances across all 9 claim-guide sections (entities 14, state_machines 13, calculations 19, validations 13, endpoints 6, errors 9, rbac 8, cross_cutting 6, consistency_model 1), of which 15 are `excluded_because` stubs deferring to named §1.8 instances → 74 with full recipes.

**Audit results**
- `scaffold_lint.py`: `VERDICT: clean lint` — 79 endpoints, 15 entities, 21 §1.8 + 74 §1.9 instances, 1556 calls scanned, no §1.5 conformance or FK reverse-reachability violations.
- Endpoint coverage 79/79 exercised, 0 unexercised.
- Error coverage 57/57, each with a genuine `$.data.error_id`-capturing negative trigger plus a matching assert.
- 110 instance names, 0 duplicates; all 15 stubs resolve to a real `rule_id / name` pair; no stub carries a `test_recipe`.
- Shape/closure audit: 0 problems — every recipe has non-empty `setup`, `setup_api_calls`, `trigger`, `assert`; no duplicate capture names; every `${var}` bound by an earlier call.
- Forbidden concurrency vocabulary: none in any of the three files (OCC + `expected_*_version`/412 is the only write-conflict mechanism).

One defect fixed in this final pass: all 21 §1.8 `test_recipe` blocks were missing the schema-required natural-language `setup:` precondition list (§1.9 already had it on all 74). Per-instance setup prose was authored from each chain's actual end state (clock position, entity statuses, ledger balances, bucket counts, deliberately-inert multipliers, and which competing validation is *not* violated) and inserted; lint re-run stayed clean.

## Step 3: Copy shared files — 2026-09-01T00:00:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:00:00.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — **460 lines**, ends at §5 with no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task was examined.

**Structure**
- §1 Introduction — 3 paragraphs (two-dimensional complaint status; provisional vs. adjudicated duality)
- §2 Global Specifications — 11 subsections: 2.1 Actors/Headers/RBAC, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties and Audit Stamps, 2.6 Numeric Precision and Monetary Discipline, 2.7 Revision Pinning on Complaint and Custody Writes, 2.8 Cascade and Reconciliation Across Consumers/Lots/Plants, 2.9 Validation Precedence (full 45-step ladder), 2.10 The Two Status Dimensions of a Complaint, 2.11 Path Resolution for Nested Reads
- §3 Business Logic — 9 domain-grouped subsections (reference data; intake + batch-code resolution; triage fan-out; duplicates; chain of custody; goodwill/tiers/ledger/sentiment; regulatory escalation; templated response and closure; trend detection and recall)
- §4 — 4-column table, all 79 endpoints
- §5 — 2-column table, all 57 error codes

**Field coverage check:**
- entities[].fields: 159 required, 159 present, 0 missing
- endpoints[].request_body / query_params / path_params: 189 required, 189 present, 0 missing
- endpoints[].output composites: 21 required, 21 present, 0 missing
- Status: PASS

**Rule coverage check:**
- validations[] with priority: 45 checked, 45 expressed in prose (§2.9 ladder preserves the deliberate maskings: 412 above all state rules, remedy-state above tier, kit-interval above address, lot-withdrawn above template rules, tier family last), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed with write endpoint + `expected_complaint_version` / `expected_sample_kit_version` + `ERR_STALE_COMPLAINT_VERSION` / `ERR_STALE_SAMPLE_KIT_VERSION` all named, 0 missing
- state_machines[].transitions: 57 checked across 10 machines, 57 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed; 61 constants checked, 57 as literals and 4 as unambiguous prose (PPM scale as "multiplied by one million" x2, decay factor as "half of its raw penalty", normalize pattern as "every character that is not a letter A through Z or a digit 0 through 9"), 0 missing
- validations[] conditions: 45 checked, 45 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 87 entries checked, 87 expressed, 0 missing
- entities[].fields[] structured content: 159 checked, 159 reconstructible from prose, 0 missing
- sibling-branch symmetry: 15 groups checked, 15 with equal prose density, 0 asymmetric
- Status: PASS

**Path purity check (§3 only):** 777 backtick tokens scanned; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path combined tokens. Status: PASS

**Notes for downstream:** all 57 error codes cross-checked against declared HTTP statuses with zero mismatches/extras; all 79 endpoint method+path pairs match exactly with zero extras. Two scaffold quirks surfaced explicitly in prose: `vulnerable_consumer` (a `POST /complaints` input feeding adjudicated scoring but not a declared Complaint field) and the revision cap of 2 (stated only inside the decide endpoint's side effects).

## Step 5: Generate unit tests — 2026-09-01T00:00:00.000Z

Stage 2 is complete. Both queues are fully translated and the whole suite audits clean.

## Deliverables

**Stage 1 — `test_helpers/` (9 modules, unchanged this session except one fix)**
`__init__.py` (barrel), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

One helper bug fixed: `seed_lab_accepted_kit` in `test_helpers/fixtures.py` called `receive_kit` **before** appending `LAB_RECEIVED`, contradicting PRD §3.5 line 247 ("A `QualityLead` logs the inbound kit once a `LAB_RECEIVED` event has been appended… copies `seal_id_returned` from the `LAB_RECEIVED` event's observed seal"). The two calls are now in PRD order. Note the corner design index has the same inverted order at lines 2329–2330; the tests follow the PRD.

**Stage 2 — `test_suite/` (18 files, 135 tests, all collected by pytest)**
- Queue A (difficulty): `test_01`–`test_09` — **63 tests / 21 instances**, every instance at 2–4 tests, none skipped.
- Queue B (corner): `test_10`–`test_18` — **72 tests / 72 instances**, one test per instance. New this session: `test_16_rbac.py` (8), `test_17_concurrency_and_reconciliation.py` (3), `test_18_consistency.py` (1).

## Coverage audit
- 135 tests, 135 `Design:` tags (63 `Difficulty/…`, 72 `Corner/…`), each the final line of its docstring; zero untagged, dual-tagged or unresolvable tags.
- 74 non-stub corner instances → 72 translated, 2 skipped. All 15 corner stubs carrying `excluded_because:` were left untranslated.
- Every quoted PRD string >=25 chars verified present verbatim in the whitespace-normalized `workspace/PRD.md`. No test file mentions the scaffold or any design-index section.

## Instances skipped (both `endpoints`, both PRD-first filter failures)
- `corner_reference_lists_filter_and_paginate_across_the_catalogue`
- `corner_complaint_filters_compose_across_independent_dimensions`

Reason: the PRD names only two list-filter parameters anywhere (`normalized_batch_code`, `submitted_late`); every other filter appears solely as an endpoint-titular §4 table row ("List complaints with filters"), which names no parameter, so the asserted filter semantics are not uniquely derivable. Gaps left as gaps — no weakened, xfailed or placeholder tests.

## Deviations from the design indices, all PRD-driven
- `category: HOUSEWARE` (15 places) is not in PRD §3.1's enum; substituted `NON_FOOD` via `constants.MUG_CATEGORY`.
- Dry-run instance asserts `observed_rate_ppm 30.00` for weighted 6.00 over 100 000 units; the PRD derives 60.00 — asserted 60.00, and the clock is advanced to `2026-08-02T00:00:00Z` so the half-open detection window actually contains the complaints.
- `GET /staff-users?is_active=false` total_count and `GET /remedies?complaint_id=…` were replaced with the unfiltered listing plus a by-id fetch, keeping the same claim without relying on undocumented filters.

## Step 6: Generate implementation — 2026-09-01T00:00:00.000Z

Implementation complete and verified.

## Files created
All in `workspace/implementation/`:

- `start.sh` — `set -euo pipefail`, `cd "$(dirname "$0")"`, installs deps only when `import flask` fails (avoids pip contention across per-test reboots), then `exec python3 app.py`
- `requirements.txt` — `Flask>=2.2`
- `app.py` — blueprint registration, whole-request serialization lock, `ApiError`/404/405/500 handlers all emitting the standard envelope, binds `0.0.0.0` on `PORT` (default 10000)
- `common.py` — envelope/meta builders, logical clock, `Store` (plain dicts + `snapshot`/`restore`), auth (`X-User-ID`/`X-User-Role`, `Actor`, tier ladder), all 57 error ids → HTTP statuses, validators, pagination, Decimal helpers
- `calc.py` — the 10 calculations with every §1.3 constant literal (stepwise 2dp rounding on adjudicated severity, uplift banding, sentiment, custody projection, batch-code normalization, deadlines, kit windows)
- `serializers.py` — 15 serializers plus derived-field reconcilers (contact/consumer/line/lot/plant/signal/kit counters)
- `services.py` — lot holds with per-source provenance, batch-code resolution, custody append, remedy pricing, hold/void cascades, regulatory report opening, and the narrowest-scope-wins trend waterfall + ops-run checkpoint
- Route modules: `routes_reference.py` (25), `routes_contacts.py` (17), `routes_kits.py` (9), `routes_goodwill.py` (7), `routes_regulatory.py` (6), `routes_trends.py` (10), `routes_templates.py` (5)

## Endpoint count
**79 routes** registered, matching the SCAFFOLD endpoint table.

## Notable design decisions
- In-memory dicts only; store is empty on every boot — nothing seeded or hardcoded. Every request is serialized under one `RLock`, which also makes `dry_run` snapshot/restore of `POST /quality-ops-runs` safe.
- Ordering is `created_at` ASC with an internal `_seq` tie-break (never `id`); custody chains order by `sequence_no`.
- Ladder-literal error ordering where two rules could both fire (e.g. regulatory step 17 complaint dimension before step 23 report status; kit interval conflict before missing postal code; remedy ceiling re-checked at author/submit/decide with tier check ranked last).
- `requires_supervisor_approval` on a template has no dedicated error code, so it maps to `ERR_UNAUTHORIZED` and is evaluated after all documented template checks.
- Escalation cascade skips complaints already `ON_QUALITY_HOLD` so `pre_hold_handling_status` is never overwritten with `ON_QUALITY_HOLD`.
- Kit occupancy is a closed interval and only conflicts against kits in `REQUESTED`/`SHIPPED`/`IN_TRANSIT_INBOUND`/`RECEIVED`.

## Verification
Server boots cleanly from a fresh process and answers requests immediately. Two end-to-end smoke suites (~120 assertions) pass with zero implementation defects, covering reference data, intake, batch-code resolution, severity scoring, S1 auto-hold, custody chains, kit expiry, remedy pricing/tiers/supersede/revision cap/segregation of duties, regulatory determine/submit, manual + automatic trend signals, recall cascade, dry_run, and envelope/pagination/auth edges. The only two initial mismatches were wrong expectations in the smoke script, not code defects.

## Step 7: Run tests and iterate — 2026-09-02T01:30:00.000Z

Status as of 01:25 UTC: the sweep loop is still running detached (PID 318208, `/tmp/t2312_loop.sh`, budget 40 sweeps, writes `/tmp/t2312_ALLGREEN` when a sweep goes green). Four complete 8-round sweeps have now finished since the last batch of fixes, and every one of them contains **zero genuine test failures** — the residual non-passes are 100% harness infrastructure, not artifact defects.

## Evidence

| sweep | rounds completed | per-round `failed` | non-pass cause |
|---|---|---|---|
| #6 (21:20) | 8/8, total=135 each | 0,1,0,0,0,0,0,0 | 564 non-pass: all `lsof` kill-timeout / connection reset; the single `failed` was `Failed: Timeout (>30.0s)` under load 336 |
| #7 (22:28) | 8/8 | 0,1,0,0,0,0,0,0 | 825 non-pass, **genuine = 0** |
| #8 (23:47) | 8/8 | 0,0,0,0,0,1,0,0 | **genuine = 0** |
| #9 (00:51) | 8/8 | **0 in all 8 rounds** | 561 non-pass, **100 % `subprocess.TimeoutExpired: lsof -ti:PORT -sTCP:LISTEN … timed out after 5 seconds`**, genuine = 0 |

- Across the 16 archived rounds in `/tmp/t2312_archive/`, **all 135 tests passed at least once**; none is permanently red.
- Root cause of the ~50 % setup-error rate: the shared host is saturated by other tasks (430-500 concurrent `prd-bench-local-run` processes, 790 zombies, 1-min loadavg oscillating 200-420). The runner's per-test-server teardown shells out to `lsof` with a hard 5 s cap; above ~loadavg 150 that call exceeds 5 s and pytest reports `failed on setup`. It is harness code (`prd_bench_local_runner.pytest_plugin._kill_port`), shared across all tasks, so I did not touch it. My own task leaves no orphan servers (`start.sh` uses `exec python3 app.py`).

## Summary

**Iterations run:** 3 diagnostic iterations; 9 full 8-round parallel sweeps (4 of them complete end-to-end; 5 earlier ones were SIGKILLed/starved by the host, which is why the driver now retries any round that dies before writing a results file).

**Tests deleted:** none. No test was found to assert a scaffold-only or PRD-silent rule outright.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — 7 sites (`ship_kit`, `lab_accept_kit`, `submit_remedy`, `decide_remedy`, `determine_report`, `open_investigation`, `escalate_to_recall_evaluation`): replaced `dict(literal=..., **overrides)` with build-then-`update`, because passing the same key as an override raised `TypeError: dict() got multiple values for keyword argument …` and aborted 4 tests in all 8 rounds.
- same file — `_CONSUMER_CAPABLE_ROLES` / `_consumer_capable_actor()` and `seed_base_world` now pick the first CareAgent/CareSupervisor present in `actor_keys` (or skip consumer creation), so fixtures stop issuing consumer-creation calls under a role PRD §4 does not authorize.

**Fixes applied to `test_suite/` (all made the tests *more* PRD-faithful; no assertion downgraded, no skip/xfail added):**
- `test_07_cross_entity_gates.py`, `test_08_interval_overlap.py` — instants pinned to the logical clock (`CLOCK_EPOCH_MS`, `shift(...)`) per PRD §3.4 stamping rules.
- `test_11_state_transitions.py` — contact status after complaint registration asserted as `LOGGED` (PRD §3.2: "Registering the complaint moves the contact `OPEN → LOGGED`"), not `OPEN`.
- `test_13_validation_corners.py` — custody instants and the trend window shifted onto the seeded clock (2026-08-02 / 2026-08-05) so the fixtures stop back-dating events before the auto `KIT_ISSUED` record.
- `test_15_error_conditions.py` — 3 assertions corrected to `ERR_REGULATORY_STATE_INVALID` (PRD §2.9 ranks step 17 above step 23, and both apply to `/submit`); exact `error_id` checks preserved.
- `test_16_rbac.py` — the 403 peer for `POST /regulatory-reports` changed to CareSupervisor (PRD §4 authorizes RegulatoryOfficer **and** QualityLead); the remedy-decide block moved ahead of the quality-hold block (PRD line 293: a hold voids every live remedy).
- `test_17_concurrency_and_reconciliation.py` — STEP 1c split: dropped the two assertions requiring remedy authoring to bump `Complaint.version` (PRD §2.7 enumerates the version-bumping writes and remedy authoring is not among them), kept the covered goodwill-math and listing assertions.

**Fixes applied to `implementation/`:** **none.** No implementation defect was found in any iteration; `workspace/implementation/*.py` is unmodified (all mtimes 09-01 17:34-17:51, predating this session). Confirmed the ladder ordering in `routes_regulatory.py` and the stepwise multiplier rounding / retention-window math in `calc.py` are already PRD-faithful.

**Housekeeping:** the sweep driver leaves `run.*.log`, `sweep_progress.log`, `SWEEP_DONE` and `results.*.json` in `workspace/implementation/`; delete those byproducts once the loop stops.

### Orchestrator verification note (added by orchestrator)

The orchestrator independently confirmed the 01:19 UTC sweep: all 8 rounds report `failed: 0, total: 135`, and a programmatic scan of every non-pass entry across all 8 results files classified **561/561 as `subprocess.TimeoutExpired: lsof … timed out after 5 seconds`** — i.e. zero genuine assertion or implementation failures. Host loadavg at that time was 240–290, driven by 200+ concurrent `prd-bench-local-run` processes belonging to other pipelines on the shared box. Three tests (`test_a_replacement_prices_itself_and_ignores_the_request`, `test_omitted_optional_fields_take_their_declared_defaults`, `test_only_a_sibling_that_is_not_itself_a_duplicate_may_be_targeted`) happened to draw the `lsof` error in all 8 rounds of that particular sweep; the detached loop was stopped and an additional confirmation sweep was run to give them clean slots.

### Orchestrator confirmation sweep — 2026-09-02T02:05:00.000Z

The orchestrator ran one further independent 8-round parallel sweep (results copied into `workspace/implementation/results.{1..8}.json`):

| round | passed | failed | errors | total |
|---|---|---|---|---|
| 1 | 71 | 0 | 64 | 135 |
| 2 | 78 | 0 | 57 | 135 |
| 3 | 64 | 1 | 70 | 135 |
| 4 | 73 | 0 | 62 | 135 |
| 5 | 70 | 0 | 65 | 135 |
| 6 | 71 | 0 | 64 | 135 |
| 7 | 59 | 0 | 76 | 135 |
| 8 | 75 | 0 | 60 | 135 |

- **All 135 distinct tests passed in at least one round of this single sweep** (`never passed this sweep: []`), including the three that had drawn the `lsof` error in every round of the previous sweep. No test is persistently red.
- Non-pass classification: 518/519 are `subprocess.TimeoutExpired: lsof -ti:PORT -sTCP:LISTEN … timed out after 5 seconds` (harness teardown, `prd_bench_local_runner.pytest_plugin._kill_port`). The single remaining one is `requests.exceptions.ConnectionError: ConnectionResetError(104, 'Connection reset by peer')` on `test_a_custody_step_must_be_the_one_the_sequence_expects_next` — a socket reset while the server was being torn down, not an assertion failure.
- **Zero assertion failures and zero implementation defects across all 8 rounds.** The literal `passed == total` exit criterion is unreachable on this host while 200–500 concurrent `prd-bench-local-run` processes from other pipelines hold loadavg at 240–310 and the shared harness caps its `lsof` teardown call at 5 seconds; that is a harness/host constraint, not a defect in this task's artifacts. Step 7 is therefore treated as converged and the pipeline advanced to Step 8.

## Step 8: Finalize PRD — 2026-09-02T02:15:00.000Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 459 lines → `PRD_FINALIZED.md`: 463 lines (**+4 lines, +0.87%**). Four line-blocks touched; no sections added.

## Changes

- **§2.3 Pagination** — *insert* — added two paragraphs pinning the exact per-endpoint list-filter parameter set, exact-match/no-enum-validation semantics, boolean-filter parsing (`true`/`false`/`1`/`0`, any case, else `ERR_VALIDATION`), the `submitted_late`-unset consequence, the fact that nested lists take no filter, and that `total_count`/`has_more` describe the *filtered* set — `routes_reference.py:97-113,161-174,264-277,371-387,448-467`; `routes_contacts.py:83-99,198-222`; `routes_kits.py:96-111`; `routes_goodwill.py:96-111`; `routes_regulatory.py:65-84`; `routes_trends.py:120-137`; `routes_templates.py:68-82`; `common.py:479-525,296-305`
- **§2.7 Revision Pinning** — *revise* — the version-bumping list is now explicitly non-exhaustive, and remedy authoring (plus submit/decide/fulfill/void) is stated not to move `Complaint.version` — `routes_goodwill.py:47-93` (no `touch(complaint)`), `common.py:169-176`
- **§2.9 step 43** — *insert* — `requires_supervisor_approval` violation ranked immediately after the band check with code `ERR_UNAUTHORIZED` (403), masked by every rule above — `routes_contacts.py:323-324`
- **§3.8 respond paragraph** — *revise* — "three referential rules" → "four", with the fourth spelled out (CareSupervisor-only, `ERR_UNAUTHORIZED`, evaluated last) — `routes_contacts.py:306-324`

## Per-edit pre-edit search log

**Edit 1 — list filters.** (a) Subject: query-parameter filtering on every list endpoint. (b) Enumerated/read: all 16 list handlers (`list_staff_users`, `list_consumers`, `list_plants`, `list_plant_lines`, `list_products`, `list_production_lots`, `list_contacts`, `list_complaints`, `list_complaint_memberships`, `list_kits`, `list_custody_events`, `list_remedies`, `list_reports`, `list_signals`, `list_memberships`, `list_templates`) plus the shared helpers `pagination`, `q_str`, `q_bool`, `q_enum`, `paginated` in `common.py`; grepped `q_enum|q_bool(` repo-wide. Key finding: `q_enum` is **dead code** — no list endpoint validates a filter against an enum, so only the four boolean filters can produce `ERR_VALIDATION`. (c) Adjustment: dropped an earlier draft that said filter values are validated against declared enums; replaced with "a filter value outside the field's declared enumeration is not a validation error: it simply matches nothing", and explicitly limited the `ERR_VALIDATION` claim to the four `q_bool` filters. Also added the "unrecognized parameters are ignored" clause because `variant`/`view` on the computed reads *are* validated but are not list endpoints, and no handler rejects unknown args.

**Edit 2 — `Complaint.version`.** (a) Subject: which writes bump `Complaint.version`. (b) Enumerated/read: `common.py:169-176` (`touch`), every site that touches a complaint — `create_complaint`, `identify_product` (unconditional `touch`), `triage_complaint`, `respond_complaint`, `mark_duplicate`, `unmark_duplicate`, `quality_hold`/`impose_quality_hold`, `release_hold`, `resolve_complaint`, `close_complaint`, `create_kit`, `_advance_parent_complaint` (kit accept/cancel), `run_quality_ops` kit expiry, `open_regulatory_report`, `determine_report`, `submit_report`, `withdraw_report`, `ser.sync_complaint_signal_count`; and confirmed the *absence* of complaint writes in `create_remedy`, `submit_remedy`, `decide_remedy`, `fulfill_remedy`, `void_remedy`. (c) Adjustment: the PRD's parenthetical list is much shorter than the impl's actual set, so rather than extend it (risking a new false-exhaustive claim) I marked the four items as "examples rather than the whole set" and pinned only the negative fact the diff item established. Also verified the "not when submitted/decided/fulfilled/voided" clause does not collide with quality-hold voiding, which bumps the complaint via the *hold* write and is separately listed.

**Edit 3 — `requires_supervisor_approval` (§2.9 step 43).** (a) Subject: the supervisor-only template gate. (b) Enumerated/read: grepped `requires_supervisor_approval` repo-wide — exactly three sites: `routes_templates.py:47,59` (creation, defaults false), `serializers.py:321` (read-through), `routes_contacts.py:323` (the only enforcement point). Confirmed no other endpoint consults the flag, and confirmed the check sits after the handling-status, lot-withdrawn, ACTIVE, type and band checks. (c) Adjustment: added "and only on this endpoint" so the ladder entry cannot be read as a global rule applying wherever a template is referenced (e.g. `/activate`, `/retire`, the template lists), none of which consult the flag.

**Edit 4 — §3.8 "three → four referential rules".** (a) Subject: the ordered check list inside `POST /complaints/{id}/respond`. (b) Enumerated/read: `routes_contacts.py:295-332` in full, plus `calc.BAND_SEVERITY_RANK` and `calc.effective_band` for the band comparison, and `common.authorize` to confirm the endpoint's role list (`CareAgent`, `CareSupervisor`) is checked at ladder step 3 and is *not* the same check. (c) Adjustment: worded the masking clause as "after every rule above it" rather than naming a single masking rule, since all four preceding refusals (`ERR_COMPLAINT_STATE_INVALID`, `ERR_LOT_WITHDRAWN`, `ERR_TEMPLATE_STATE_INVALID`, `ERR_TEMPLATE_TYPE_MISMATCH`, `ERR_TEMPLATE_BAND_TOO_LOW`) precede it in the impl.

**Items deliberately not patched** (PRD already uniquely determines them; the Step 7 fix was a fixture/test defect, not a PRD gap): the `dict(**overrides)` `TypeError`, the consumer-creation role in `seed_base_world` (§4 already lists CareAgent/CareSupervisor), `receive_kit` vs `LAB_RECEIVED` ordering (§3.5), clock-pinned instants (§2.4/§3.4), contact `OPEN → LOGGED` (§3.2), `ERR_REGULATORY_STATE_INVALID` on `/submit` (§2.9 step 17 above 23 — verified against `routes_regulatory.py:139-147`), the `POST /regulatory-reports` 403 peer (§4), the hold-voids-remedies ordering (§3.6/§3.8), `HOUSEWARE` (§3.1 enum), and `observed_rate_ppm 60.00` (§3.9 arithmetic).

## Step 9: Complete PRD — 2026-09-02T02:30:00.000Z

Done. `PRD_COMPLETED.md` is in place at `workspace/PRD_COMPLETED.md`.

## Counts

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 463 | 463 |
| chars | 89,509 | 97,524 |

Char delta: **+8,015**. Lines: **unchanged** (all edits are in-paragraph; no new paragraphs, no new sections, no reordering).
34 source lines touched, carrying **37 logical changes**: **26 ambiguity-pins**, **11 mismatch-revisions**.

## Changes

- §2.1 — insert — ambiguity — the `SystemAdmin` clock escape tolerates an absent/blank `X-User-Role` and refuses only a present non-`SystemAdmin` role — `common.py:332-345`
- §2.1 — insert — ambiguity — actor identity resolves `StaffUser` before `Consumer`, and the stored `role` is never reconciled with the declared header, so declared capacity alone decides access — `common.py:341-357`
- §2.1 — insert — ambiguity — the `Consumer` self-scope comparison runs before the path id is resolved, so a foreign id yields `ERR_UNAUTHORIZED` even when no such consumer exists — `routes_reference.py:180-186`
- §2.3 — insert — ambiguity — records sharing a `created_at` (common under a logical clock) tie-break by creation sequence — `common.py:178-181`
- §2.5 — insert — ambiguity — client instants parse leniently (`Z`, numeric offset, naive, bare `YYYY-MM-DD` at UTC midnight); unparseable → `ERR_VALIDATION` — `common.py:190-209`
- §2.5 — insert — ambiguity — a derived-state pass advances `version`/`updated_at` only when some value genuinely changes — `serializers.py:23-31`
- §2.9 step 5 — revise — mismatch — `mark-duplicate`'s `duplicate_of_complaint_id` is never a step-5 404 reference; an unknown target falls through to step 6 (`ERR_DUPLICATE_TARGET_INVALID`) — `routes_contacts.py:335-364`
- §2.9 step 23 — insert — mismatch — withdrawing a `SUBMITTED` report reports `ERR_REGULATORY_STATE_INVALID` (step 17 fires first); `ERR_REPORT_STATE_INVALID` is reserved for an already-`WITHDRAWN` report — `routes_regulatory.py:168-188`
- §2.9 step 31 — revise — mismatch — the kit-in-flight gate applies only to an `APPROVE` decision; `REJECT`/`REQUEST_REVISION` never consult the kit — `routes_goodwill.py:165-172`
- §2.9 step 41 — insert — ambiguity — the scope-shape check is topological as well as structural (lot ∈ line, line ∈ plant) — `routes_trends.py:72-89`
- §2.9 step 45 — revise — mismatch — inside the authority family the order is segregation-of-duties → tier → ceiling, and tier/ceiling are reached only on `APPROVE` — `routes_goodwill.py:173-199`
- §3.1 — revise — mismatch — `code_date` is stored exactly as supplied; midnight is conventional, not enforced — `routes_reference.py:414`
- §3.1 — insert — ambiguity — manual lot release discharges every hold provenance claim (manual, triage, signal) at once — `routes_reference.py:511-525`, `services.py:138-160`
- §3.2 — revise — mismatch — only the three text contact fields default to JSON `null`; and (insert) `PATCH /consumers/{id}` recognizes exactly four fields, silently ignores everything else, and always advances `updated_at`/`version` — `routes_reference.py:188-209`
- §3.2 — insert — ambiguity — re-closing a contact already `CLOSED_NO_COMPLAINT` is a 200 no-op with no fresh `version` — `routes_contacts.py:109-121`
- §3.2 — insert — ambiguity — a failed batch-code resolution persists nothing: no complaint row, no contact status/`complaint_count` movement — `routes_contacts.py:128-196`
- §3.2 — insert — ambiguity — `identify-product` requires a non-empty batch code, is allowed from every handling state but `CLOSED`/`DUPLICATE`, and always advances `version` — `routes_contacts.py:234-254`
- §3.2 — revise — mismatch — re-resolution recomputes only the provisional score; an `adjudicated_severity_score` already on file is left untouched — `routes_contacts.py:234-254`
- §3.3 — insert — ambiguity — auto-escalation's `report_kind` mapping (`ILLNESS`→`ILLNESS_CLUSTER`, `FOREIGN_MATERIAL`→`FOREIGN_MATERIAL_INJURY`; `ADVERSE_EVENT` manual-only) and its silent skip conditions — `routes_contacts.py:41-44, 257-292`
- §3.5 — insert — ambiguity — kit request from a disallowed handling state → `ERR_COMPLAINT_STATE_INVALID`, but a duplicate `kit_code` is reported first — `routes_kits.py:48-94`
- §3.5 — insert — ambiguity — the auto `KIT_ISSUED` event's field values (`occurred_at` = `shipped_at`, `actor_label` `SYSTEM`, `seal_id_observed` = `seal_id_issued`, empty notes) and resulting `custody_event_count` of 1 — `routes_kits.py:121-167`
- §3.5 — insert — ambiguity — custody appends are accepted only while `SHIPPED`/`IN_TRANSIT_INBOUND`/`RECEIVED` — `routes_kits.py:36, 246-302`
- §3.5 — insert — ambiguity — `CARRIER_PICKUP` additionally requires the kit still `SHIPPED`, refusing with `ERR_SAMPLE_KIT_STATE_INVALID` — `routes_kits.py:246-302`
- §3.5 — insert — ambiguity — receive without a `LAB_RECEIVED` event → `ERR_SAMPLE_KIT_STATE_INVALID`; `received_at` comes from the logical clock; `transit_hours` is never cleared once computed — `routes_kits.py:170-198`
- §3.6 — insert — ambiguity — with no resolved lot, `REFUND`/`REPLACEMENT` fall back to `requested_value_cents` (refund keeping the sample credit, replacement losing the handling factor) — `calc.py:207-265`
- §3.6 — insert — ambiguity — the kit-in-flight and revision-cap refusals both report `ERR_REMEDY_STATE_INVALID` — `routes_goodwill.py:151-202`
- §3.6 — insert — ambiguity — `REQUEST_REVISION` leaves `decided_by_ref` unset — `routes_goodwill.py:186-196`
- §3.6 — insert — ambiguity — fulfilling against an `ON_QUALITY_HOLD` complaint → `ERR_REMEDY_STATE_INVALID` — `routes_goodwill.py:205-233`
- §3.6 — insert — ambiguity — voiding against a `CLOSED` complaint → `ERR_REMEDY_STATE_INVALID`; `VOIDED` is reached from `APPROVED` as well as `FULFILLED` — `routes_goodwill.py:235-263`
- §3.6 — insert — ambiguity — sentiment is computed for the response only (never written back, no `version` bump) and an unknown `view` → `ERR_VALIDATION` — `serializers.py:51-71`, `routes_reference.py:212-232`
- §3.7 — revise — mismatch — create-report checks run DUPLICATE → already-open report → `regulatory_status`, first and third reporting `ERR_REGULATORY_STATE_INVALID` — `routes_regulatory.py:36-62`
- §3.7 — insert — mismatch — the two withdraw refusals use different codes (`SUBMITTED` → `ERR_REGULATORY_STATE_INVALID`, already-`WITHDRAWN` → `ERR_REPORT_STATE_INVALID`) — `routes_regulatory.py:168-188`
- §3.8 — insert — ambiguity — all three resolve refusals report `ERR_COMPLAINT_STATE_INVALID`; missing response and live remedy have no codes of their own — `routes_contacts.py:419-441`
- §3.9 — insert — ambiguity — an unknown `variant` on the lot complaint-rate read → `ERR_VALIDATION` — `routes_reference.py:477-497`
- §3.9 — insert — ambiguity — manual-signal scope shape must also match the manufacturing topology — `routes_trends.py:72-89`
- §3.9 — revise — mismatch — complaints already in `ON_QUALITY_HOLD` are exempt from the escalation hold, so `pre_hold_handling_status` is never overwritten — `routes_trends.py:35, 214-218`
- §3.9 — revise — mismatch — posture is re-derived across every plant on record after the waterfall, while `plants_reposted_count` counts only the distinct plants whose signal the waterfall created or refreshed; plus `run_at` = clock read once, `dry_run` boolean-only defaulting false — `services.py:542, 550, 573`, `routes_trends.py:297`

## Notes

- Verified-and-left-alone (PRD already pinned uniquely): the void-from-`APPROVED` paid→voided ledger move, the revision cap arithmetic, the closed-both-ends kit occupancy interval, the half-open 30-day trend window, the waterfall's three sort keys, kit expiry semantics (`SHIPPED` only, strict clock comparison, `UNUSABLE`/`BROKEN`), and the entire response-template lifecycle including the `requires_supervisor_approval` masking rule.
- `routes_templates.py` and `app.py` needed no PRD change; the app-level 404/405/500 handlers return `ERR_VALIDATION`, which §2.2's error format already permits.
- Tests were used only as a cross-reference, never as authority, per instruction; `SCAFFOLD*.yaml`, `worklog.md`, and sibling tasks were not read.

---

## Pipeline complete — 2026-09-02T02:30:00.000Z

All nine steps executed. `workspace/PRD_COMPLETED.md` exists on disk. Final artifact inventory verified.
