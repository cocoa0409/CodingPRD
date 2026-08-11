# Worklog — task_0990_textile_clothing_recycling_pickup

## Step 1: Create Task Directory — 2026-08-10T10:59:41.000Z

Pre-assigned output folder `tasks/task_0990_textile_clothing_recycling_pickup` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per headless-run instructions. Scenario: "Textile & Clothing-Recycling Pickup: bag/bin & schedule, brand/thrift partner routing, weight & diversion credit, drop-box network & fill sensor, charity split, contamination, reporting, sponsor". Difficulty parameter: "generate task hard than expert level!" (passed through to Step 2 scaffold-generator only).

## Step 2: Generate Scaffold — 2026-08-10T11:45:41.000Z

All three scaffold artifacts are generated and verified. (Note: `worklog.md` and `workspace/` pre-existed in that directory; I did not create or touch them.)

## Summary

**Scenario 990 — Textile & Clothing-Recycling Pickup**, generated fresh from the scenario text plus the skill spec (no sibling tasks consulted).

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**SCAFFOLD.yaml contents (deliberately above the Expert band per the difficulty parameter):**
- **14 entities**: ServiceZone, Resident, BagKit, PickupRequest, Partner, RoutingAssignment, DropBox, FillReading (append-only event, `common_fields: false`), WeightTicket (polymorphic source: pickup or drop-box), DiversionCredit, SponsorFund, Charity, ContaminationReport, ReportingPeriod
- **11 state machines** (44 transitions): cyclic pickup no-show/rebook loop, branching credit dispute/finalize/void/settle fork, cyclic drop-box fill→collect→OK, partner ELIGIBLE⇄SUSPENDED + QUARANTINED posture machine, plus resident/kit/fund/report/period machines
- **2 OCC concurrency rules** (reschedule on PickupRequest.version; charity-split on ServiceZone.version), both 412/ERR_STALE_VERSION
- **9 calculations**: dual-variant credit projection (provisional vs certified), combinatorial credit value with fund-capped nested-min sponsor bonus (mode a), per-line-floor charity split rounding (mode b), dual-variant partner scoring (30-day rolling vs half-life decay), fill/strike thresholds, fund ledger waterfall with conservation invariant, half-open reporting-window aggregation
- **11 validation priorities**: auth → authz/ownership → request shape → existence → state → OCC → safety (quarantine) → temporal → constraint → referential → fiscal, with two engineered priority conflicts (state-vs-fiscal, safety-vs-constraint)
- **66 endpoints** (incl. `POST /_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`); every FK has a reverse-reachability GET
- **32 error codes**, all referenced from validations/transitions/endpoints
- **8 roles** (peer_roles model): ZoneOperator, Resident, Driver, PartnerManager, Inspector, SponsorManager, CharityAdmin, SensorGateway — entity-backed where ownership matters, opaque otherwise

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances — exactly 2 per each of the 9 difficulty rules, each with structured `setup_api_calls`/`trigger`/`assert`, all `${var}` placeholders bound by captures, all formula-derived asserts precomputed as literals (e.g., 2480 vs 1650 credit divergence, 537/537/555 split rounding, routing_score 100 vs report_score 94.05 at +40 days, exact-800 kg route capacity).

**SCAFFOLD_CORNER_DESIGN.yaml**: 61 instances across all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model) — 51 full test recipes + 10 `excluded_because` stubs referencing difficulty instances.

**Verification**: `scaffold_lint.py` verdict, verbatim:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(66 endpoints, 14 entities, 18 §1.8 + 51 §1.9 active instances, 654 calls scanned, 0 violations.) Additional self-checks passed: no dangling `grounds:` refs, no forbidden race vocabulary, envelope verbatim, file split honored, endpoint roles ⊆ RBAC roles, all errors referenced, no cross-file name collisions.

One design note: the global `{param}` → `{id}` path-placeholder rename was required because lint check (f) matches sub-resource prefixes against the literal segment `{id}`; all paths here are single-parameter, so the rename is semantics-preserving and consistent across all three files.

## Step 3: Copy Shared Files — 2026-08-10T11:46:08.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0990_textile_clothing_recycling_pickup/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T11:52:12.000Z

All checks pass. PRD generation is complete.

---

## PRD Generation Summary

**Output file**: `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/workspace/PRD.md` (exists on disk, 343 lines, 8,468 words, ~58 KB)

### Section list
- **§1. Introduction** — 3 paragraphs (programme framing, three compounding pressures, audience)
- **§2. Global Specifications** — 11 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties (incl. FillReading's `updated_at`/`version` absence), 2.5 Nested Resource Retrieval, 2.6 Monetary Values & Rounding (rates 120/45/20, contamination multipliers 1.0/0.9/0.5/0.0, bulk threshold 20.0 kg / 500 cents, sponsor 10%), 2.7 OCC (two endpoints), 2.8 Sponsor Fund Ledger, 2.9 Partner Quality Scores (rolling vs decay-weighted variants), 2.10 Logical Clock (startup `2026-05-01T00:00:00Z`), 2.11 Validation Ordering (all 11 priorities in declared sub-order)
- **§3. Business Logic & Workflows** — 8 subsections organized by domain lifecycle: zone/resident/charity enrolment → kits → pickup lifecycle → drop boxes & sensors → weigh/certify → contamination & cascades → routing & credit pipeline → reporting periods
- **§4. Endpoint Definitions** — 4-column table, all 66 endpoints present
- **§5. Error Code Catalogue** — 2-column table, all 32 errors present

### Coverage of scaffold sections
All §1.0–§1.7 scaffold tables projected: response envelope (verbatim §2.2), 14 entities, 7 state machines, 9 calculations, 11 validation priorities, 66 endpoints, 32 errors, 8 roles (with identity prose for entity-backed vs opaque).

### Hard Contracts (all PASS)
- **Contract 1 Field-Name Coverage**: 79 required, 79 present, 0 missing. (Initial pass missed `dropbox_id`, `partner_type`, `sponsor_name`, `ticket_id`; repaired via targeted sentence insertions in §3.4, §3.7, §2.8, §3.7.)
- **Contract 2 Rule Coverage**: All state-transition preconditions/side-effects, both OCC rules (`expected_pickup_version`/`expected_zone_version` → `ERR_STALE_VERSION` 412), all 9 calculations (estimated_pickup_weight, projected_credit_cents_rule with both variants, diversion_credit_value with pinned 5-step order and headroom cap, charity_split_allocation with floor-then-remainder order and drop-box largest-pct tiebreak, partner_quality_scores dual variant, dropbox_fill_posture with inclusive 85.0/50.0 boundaries, resident_strike_accumulation with inclusive 3-strike limit, sponsor_fund_ledger invariant, reporting_period_aggregation 7 fields), all 11 validation priorities with declared sub-order, all endpoint side effects, all sibling transitions rendered with equal density.
- **Contract 3 §3 Path Purity**: 552 backtick tokens in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos.

### Key Zero-Silence / precision decisions
- **§2.2 emitted verbatim** (canonical `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `"data": { }` left empty).
- **FillReading exception** called out explicitly in §2.4 (no `updated_at`, no `version`).
- **Logical clock startup default** stated in §2.10 and §4 row.
- **Contamination cascade fan-out** (§3.6) lists every side-effect: credit void + hold release, PENDING assignment decline with `SYSTEM_QUARANTINE`, partner quarantine from `ELIGIBLE` or `SUSPENDED`, resident strike + suspension sub-cascade.
- **Finalize-from-DISPUTED hold-reuse rule** stated explicitly (no second hold placed when `has_hold` was already true).
- **Adjacent-period allowance** stated for `ERR_PERIOD_OVERLAP` (half-open windows).
- **Route capacity boundary**: exactly 800.0 kg allowed.
- **Buffered overlap**: exactly-30-minute gap permitted.
- **Score-floor boundary**: `routing_score < 40` suspends, `>= 40` reinstates; read-trigger recompute never fires status transitions.
- **Driver identity exception** to opaque-role rule stated (mark-collected/mark-no-show require `X-User-ID == driver_id` on ROUTED pickups).
- **Validation priority 9 sub-order** (a)–(k) enumerated in §2.11 so sub-ordering is not silently lost.
- **No test-targeting content** from `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read, opened, or referenced; both files remained untouched.

## Step 5: Generate Unit Tests — 2026-08-10T12:20:40.000Z

All validation gates pass. Final state on disk:

## Summary

**Output directories confirmed on disk:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/test_helpers/` — 9 files: `types.py` (14 entity TypedDicts incl. append-only `FillReading` without `updated_at`/`version`, 17 status/role enums), `api_client.py` (66 endpoint methods, `ApiClient(GenericApiClient)`), `api_errors.py` (31 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + fund-ledger / capacity-partition invariants), `factories.py`, `constants.py` (all PRD thresholds: 4.0 kg/bag, rates 120/45/20, multipliers, 500/20.0 bulk, 10% bonus, 800.0 kg capacity, 85.0/50.0 fill, floor 40, caps 3/2), `test_users.py` (shared constants for opaque roles + `make_*_headers` builders for all four entity-backed roles and driver-binding), `fixtures.py` (layered chains: kit delivery, pickup→route→collect, `ctx_collected/ctx_certified/ctx_credit/ctx_finalized/ctx_settled`, box fill/collect, selector, reports, clock, split replacement).
- `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/test_suite/` — `conftest.py` + 9 numbered test files.

**Tests emitted: 87 total**
- Queue A (Difficulty): **36 tests — all 18 instances × 2**, zero skipped.
- Queue B (Corner): **51 tests — all 51 non-stub instances × 1**, zero skipped. The 10 `excluded_because:` stubs were correctly not translated; every stub's `difficulty_instance` cross-reference verified resolving to a real §1.8 instance.

**Instances skipped: 0.** Every instance passed the PRD-first two-condition filter. Three derivability adjustments were made inside otherwise-faithful translations (assertions relaxed, instances still covered): (1) PRD never pins the initial `version` value to 1, so OCC/reschedule-limit tests assert captured+1 increments and PRD-pinned `reschedule_count` (starts at 0) instead of literal versions; (2) `certified_at`/`last_collected_at` instants are pinned to the default clock but their exact string rendering is not, so prefix equality on `2026-05-01T00:00:00` is used; (3) the charity allocations computed read asserts `total_received_cents == 990` plus presence of the 990-cent line (`amount_cents` is PRD-named) rather than the full line shape.

**Stage 2 validation results:**
- Tag audit: 87/87 tests carry exactly one `Design:` tag; all tags resolve to real instances; 0 untagged / dual-tagged / bad / stub-pointing tags; difficulty ≥2 and corner ≥1 coverage complete.
- PRD citation check: every quoted citation in all 87 docstrings survives literal (whitespace-normalized) grep of `PRD.md` — 0 failures (three endpoint-table quotes were replaced with rule-bearing §2.1 prose to satisfy C1/C2).
- `pytest --collect-only`: 87/87 collected cleanly; `compileall` passes; no `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code.

## Step 6: Generate Implementation — 2026-08-10T12:20:40.000Z

All verified. Implementation is complete and on disk.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/workspace/implementation/`

**File list (17 source files + launcher + requirements):**
- `start.sh` — foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op once Flask present), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` (flask), `app.py` (blueprint registration + envelope-ized 404/405/500 handlers)
- `db.py` (empty in-memory store, logical clock defaulting to `2026-05-01T00:00:00Z`, version/timestamp bookkeeping), `errors.py` (all 31 catalog IDs), `response.py` (`meta`/`response_type`/`data` envelope, `req_` IDs, pagination fields `limit`/`offset`/`total_count`/`has_more`), `middleware.py` (X-User-ID/X-User-Role auth, 8 roles, per-route lock), `util.py` (field/datetime/pagination validation)
- `services/calc.py` (all money/score math in `Decimal`, ROUND_HALF_UP), `services/domain.py` (serializers, computed views, cascades, selector)
- `routes/`: zones, residents, kits, pickups, partners, dropboxes, tickets, reports, credits, funds, charities, periods, clock

**Endpoint count:** 66 registered routes — matches the scaffold's 66-endpoint table exactly.

**State machines implemented (11):** Resident (strike-suspension cascade + reactivate), BagKit (REQUESTED→DISPATCHED→DELIVERED→RETIRED + auto-retire on collection), PickupRequest (SCHEDULED self-loop reschedule with OCC, ROUTED/COLLECTED/WEIGHED/SETTLED bubble-ups, NO_SHOW→rebook cycle, cancel rules), Partner (ELIGIBLE↔SUSPENDED on score recompute, QUARANTINED, remediate two-step), RoutingAssignment (PENDING→ACCEPTED/DECLINED→COMPLETED, SYSTEM_QUARANTINE auto-decline), DropBox (OK/FILLING/FULL_PENDING_COLLECTION posture cycle), WeightTicket (PROVISIONAL→CERTIFIED→QUARANTINED/VOIDED with full cascades), DiversionCredit (PROVISIONAL/FINALIZED/DISPUTED/SETTLED/VOIDED with hold retention on dispute), SponsorFund (ACTIVE→CLOSED with zero-hold gate), ContaminationReport (OPEN→ADJUDICATED/DISMISSED with UPHELD cascades), ReportingPeriod (OPEN→CLOSED with frozen aggregates).

**Calculations implemented (9):** est weight (bags × 4.0); provisional credit projection; final credit value with pinned 5-step order (base→contamination→bulk→headroom-capped sponsor bonus) and integer-cent round-half-up at each step; charity split with floor-per-line-then-remainder (resident absorbs for pickups, largest-pct charity for drop boxes); dual-variant partner scores (30-day rolling integer routing_score vs decay-weighted 2dp report_score, penalties 20/15/0, floor 40); fill posture thresholds (inclusive 85.0/50.0, latest-by-recorded_at with created_at tiebreak); strike accumulation (inclusive limit 3 + SCHEDULED-pickup cancel cascade); sponsor fund ledger (derived held/paid/available, invariant-conserving); reporting-period aggregation over the half-open window with all 7 frozen fields.

**Notable detail:** re-finalize of a DISPUTED credit treats its existing hold as self-headroom so the dispute→refinalize flow reuses one hold without spurious ERR_FUND_INSUFFICIENT, keeping the ledger invariant exact.

**Boot smoke tests run:** byte-compile of all files; boot via the real `bash start.sh` contract (200 on first probe); fresh-restart isolation confirmed (empty store + default clock after kill/relaunch); two suites totaling 100 assertions against a live server — full lifecycle (zone→resident→kit→pickup→route→collect→certify→partner select→accept→credit→finalize→settle with exact cent values 1688/675/422/591), dropbox collection, MINOR/SEVERE adjudication cascades (ticket quarantine, credit void + hold release, partner quarantine at score 80, resident strike, remediate→ELIGIBLE), plus edge cases: 800.0 kg capacity boundary, kit limit, ERR_BAGS_NOT_DELIVERED, ERR_NO_ELIGIBLE_PARTNER, fund insufficiency/topup/close gating, suspension at 3 strikes (403s), rebook cap 2, period overlap/adjacency, ERR_OPEN_TICKETS_REMAIN, auth 401/403/404, pagination bounds. All pass (one self-test expectation was wrong where the API correctly accepts the inclusive 60-minute minimum window).

## Step 7: Run Tests and Iterate — 2026-08-10T12:34:39.000Z

## Summary

**Exit condition met:** all 8 parallel rounds of the final sweep passed 86/86 (rounds 1–8: passed == total, 0 failed, 0 errors).

**Iterations run:** 4 sweeps (8 rounds each).

**Tests deleted (1):**
- `test_07_credits_and_funds.py::test_charity_allocations_computed_read` — COMPUTED-FIELD SILENCE / response-shape silence. PRD's only mention of `GET /charities/{id}/allocations` is the §4 endpoint-table row ("Computed read: this charity's allocation lines across all settled credits"); no PRD sentence pins the view's keys (`allocations`, `total_received_cents`) or per-line fields (`charity_id`), so two faithful readers diverge (frozen line objects verbatim vs. charity-scoped records omitting the redundant `charity_id`). The PRD-covered substance (§3.7 per-line floor, §3.1 `total_received_cents` aggregation) remains covered by `test_per_line_floor_then_remainder_to_resident`, `test_charity_totals_match_frozen_lines`, and `test_settle_executes_all_side_effects` via PRD-pinned surfaces. Scaffold rule that drove generation: the `Corner/endpoints/charity_allocations_computed_read` endpoint entry whose response shape doc-generator reduced to a one-line table description.

**Fixes applied to `test_helpers/` (2):**
- `fixtures.py` `new_zone()` — called `create_zone_payload(name)` positionally against a `**overrides`-only factory; changed to `create_zone_payload(name=name)`. Root cause of 82 tests × 8 rounds failing in iteration 1 (656 TypeErrors).
- `fixtures.py` `new_charity()` — same bug class: `create_charity_payload(name)` → `create_charity_payload(name=name)`. Root cause of 6 tests × 8 rounds failing in iteration 2.

**Fixes applied to `test_suite/` (2):**
- `test_05_tickets_and_certification.py` — added `ctx_credit` to the `test_helpers` import list (NameError in `test_duplicate_credit_rejected`, 8 rounds).
- `test_07_credits_and_funds.py` — deleted `test_charity_allocations_computed_read` (see above).

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful; every failure traced to test-side harness bugs or a PRD-silent assertion. An AST audit of all factory call sites confirmed no remaining arity mismatches, and pyflakes confirmed no remaining undefined names.

## Step 8: Finalize PRD — 2026-08-10T12:38:03.000Z

Done. The diff is exactly one revised line (line 302), the §4 endpoint-table row for `GET /charities/{id}/allocations`.

## Summary

**Line counts / %-delta:** PRD.md = 342 lines, PRD_FINALIZED.md = 342 lines — delta 0 lines, 0.00% (one line rewritten in place, none added or removed).

**Changes (one total):**
- §4 Endpoint Definitions — **revise** — the `GET /charities/{id}/allocations` table row now pins the response shape the implementation exhibits: a single object with keys `charity_id`, `total_received_cents` (same running total as the charity record), and `allocations`, where each entry carries exactly `credit_id`, `ticket_id`, `pct`, `amount_cents`, drawn from every `SETTLED` credit platform-wide with credits iterated in `created_at` ascending — `implementation/routes/charities.py:34-56` (shape at lines 46-56, sort at line 42), `implementation/services/domain.py:105,109-117` (shared `charity_total`).

**Step-7 items with no PRD edit (traced, determined not PRD-relevant):**
- `test_helpers/fixtures.py` `new_zone()` / `new_charity()` — pure test-harness bugs (positional arg passed to a `**overrides`-only factory); PRD does not specify test factories.
- `test_suite/test_05_tickets_and_certification.py` import fix — test-side NameError only.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: response shape of `GET /charities/{id}/allocations` — top-level keys, per-entry fields, iteration scope/order, and the meaning of `total_received_cents`.
- (b) Impl paths enumerated and read: `implementation/routes/charities.py` (entire file — the endpoint itself plus `GET /charities/{id}` which shares `charity_view`); `implementation/services/domain.py` (full file — `charity_view`, `charity_total`, `pub`); `implementation/services/calc.py:128-144` (`charity_split_lines` — frozen-line shape `{charity_id, pct, amount_cents}` ordered by charity `created_at` ASC); `implementation/routes/credits.py` (full file — create/settle freeze lines at lines 187-202); `implementation/routes/periods.py:62-63` (aggregates consume frozen lines' `amount_cents`); `implementation/response.py` (envelope; `response_type="object"` default, pagination only when passed — this endpoint does not paginate).
- (c) Wording adjustments from the search: (1) scoped the field list to the view's *entries* ("each entry carries ...") rather than claiming anything about the frozen credit lines themselves, because the credit's own `charity_allocations` lines do include `charity_id` (asserted verbatim by surviving tests against §3.7) — describing them as identical would have created a new mismatch with `credits.py:202`/`calc.py:141`; (2) added "platform-wide" since the impl iterates `store.credits.values()` with no zone filter; (3) tied `total_received_cents` to "the same running total carried on the charity record" since both surfaces call the identical `charity_total` function, consistent with §3.1's existing definition; (4) pinned `created_at` ascending order to match the sort at `charities.py:42` and house default §2.3, without mentioning the internal `_seq` tiebreak that is not API-visible; (5) made no pagination claim, since the endpoint returns a single object (not a §2.3 list) and the deleted test's divergence concerned keys/fields only.

PRD_FINALIZED.md is at `/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-10T12:49:15.000Z

## Summary

**Source:** `PRD_FINALIZED.md` (342 lines / 58,939 chars) → **`/home/ubuntu/github/CodingPRD/tasks/task_0990_textile_clothing_recycling_pickup/workspace/PRD_COMPLETED.md`** (343 lines / 63,001 chars; **+1 line, +4,062 chars**, 30 single-line hunks + 1 appended table row).

**Counts:** 25 ambiguity-pins, 5 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.1 — insert — ambiguity — entity-backed roles also govern reads (Resident: own record/kits/pickups/own-pickup tickets/own credits; PartnerManager: own partner + own assignments; SponsorManager: own fund, credits with `fund_id` null-or-own; CharityAdmin: own charity); ticket-scoped credit/assignment lists filter rather than reject; record-dependent bindings skipped when target missing (404), path-decidable bindings enforced before existence — middleware.py:31-49, routes/credits.py:14-22, routes/partners.py:46,117-118
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + 24 lowercase hex chars — response.py:11
- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of 1..100, negative) → `ERR_INVALID_REQUEST` 400; `created_at` ties broken by insertion order — util.py:108-143
- §2.4 — revise — ambiguity — `version` starts at **1** on creation — db.py:62
- §2.4 — revise — ambiguity — FillReading carries its event payload (`dropbox_id`, `fill_pct`, `recorded_at`) alongside `id`/`created_at` — routes/dropboxes.py:57-65
- §2.5 — insert — ambiguity — undeclared path or unsupported method → `ERR_NOT_FOUND` 404 — app.py:20-27
- §2.10 — revise — mismatch — clock set accepts **any** valid instant (no monotonicity enforced; was "advance") and returns `{current_utc: <supplied>}` — routes/clock.py:14-18
- §2.11 — revise — mismatch — step (3): non-empty body must be a JSON object; undeclared-field rejection only on endpoints with a declared body schema (bodyless endpoints ignore extra fields) — util.py:47-59, routes/kits.py:17
- §2.11 — insert — ambiguity — resident-suspension gating (`ERR_RESIDENT_SUSPENDED`) placed at step (5) with state admissibility — routes/pickups.py:48,148
- §3.1 — insert — ambiguity — split-line `pct` non-integer or outside 1..100 → `ERR_SPLIT_SUM_INVALID` — routes/zones.py:68-69
- §2.8 — insert — ambiguity — `initial_cents` must be int > 0 else `ERR_INVALID_REQUEST` — routes/funds.py:23-24
- §2.8 — revise — ambiguity — top-up requires `ACTIVE` fund (else `ERR_INVALID_STATE`) and `amount_cents` int > 0 (else `ERR_INVALID_REQUEST`) — routes/funds.py:59-64
- §2.9 — insert — ambiguity — partner reads expose derived `committed_kg`/`completed_kg`/`remaining_kg` (sums over ACCEPTED/COMPLETED assignments) — services/domain.py:51-57
- §3.3 — insert — ambiguity — `bags_claimed` < 1 → `ERR_INVALID_REQUEST` 400 — routes/pickups.py:42-43
- §3.3 — revise — ambiguity — mark-collected: non-positive `provisional_weight_kg` → `ERR_INVALID_REQUEST` 400; endpoint returns **201** carrying the created ticket — routes/pickups.py:208-209,240
- §3.3 — revise — mismatch — rebook check order pinned as impl: state (`NO_SHOW`) → resident `ACTIVE` → window checks → rebook cap (PRD prose listed cap before windows) — routes/pickups.py:145-153
- §3.4 — revise — ambiguity — box collection: non-positive weight → `ERR_INVALID_REQUEST` 400; success returns 201 with the created ticket — routes/dropboxes.py:88-89,113
- §3.5 — insert — ambiguity — new ticket's `highest_upheld_severity` starts at `NONE` — routes/pickups.py:231
- §3.5 — revise — ambiguity — non-positive `certified_weight_kg` → `ERR_INVALID_REQUEST` 400 — routes/tickets.py:37-38
- §3.6 — revise — ambiguity — `notes` defaults to empty string when omitted — routes/reports.py:35
- §3.6 — revise — ambiguity — one-open-report rule evaluated **before** the report-window rule (prose order reversed to match impl) — routes/reports.py:26-30
- §3.6 — revise — ambiguity — dismiss leaves `adjudicated_at` null — routes/reports.py:100-109
- §3.7 — revise — ambiguity — partner registration: `capacity_kg` int > 0 and non-empty valid `accepted_grades`, else `ERR_INVALID_REQUEST` 400 — routes/partners.py:24-30
- §3.7 — revise — ambiguity — finalize re-snapshots `applied_severity` from the ticket's current severity — routes/credits.py:127
- §3.7 — insert — ambiguity — re-finalize with existing hold counts the held `gross_cents` as headroom for its own sufficiency check — routes/credits.py:114-118
- §3.7 — revise — ambiguity — settle of a `FINALIZED` credit with no hold → `ERR_CREDIT_NOT_FINAL` — routes/credits.py:178-179
- §4 — revise — mismatch — 200-OK list: removed "mark-collected on the pickup side" (returns 201 with the ticket), added missing "rebook" — routes/pickups.py:161,240
- §4 table — revise — ambiguity (×5 rows) — GET /partners/{id} "PartnerManager: self only"; GET /weight-tickets/{id} "Resident: only own pickups' tickets"; GET ticket routing-assignments "PartnerManager: filtered to own"; GET ticket diversion-credits "Resident: own pickups only; SponsorManager: filtered to own fund"; GET fund diversion-credits "SponsorManager: own fund only" — routes/partners.py:46,117-118, routes/tickets.py:19-21, routes/credits.py:70-77, routes/funds.py:90-91
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row (unhandled-exception envelope) — app.py:30-34

**Not changed (already uniquely pinned):** all calculation formulas and rounding order, both score variants, posture thresholds/tie-breaks, buffered-overlap rule, route-day 800 kg rule, ledger arithmetic, cascade shapes, period aggregates, validation priority order, and the reschedule/rebook caps (PRD's "below the cap" phrasing and §2.11 sub-order already match impl: 3 reschedules / 2 rebooks allowed, window checks before cap checks — cross-confirmed by test_03 but grounded in the code).
