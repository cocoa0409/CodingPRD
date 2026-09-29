# Worklog — task_2353_digital_ordering_middleware_delivery_channel

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2353_digital_ordering_middleware_delivery_channel/` and `tasks/task_2353_digital_ordering_middleware_delivery_channel/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T05:19:00.000Z

All three artifacts are complete and the lint is clean.

## Generated files
`/home/ubuntu/github/CodingPRD/tasks/task_2353_digital_ordering_middleware_delivery_channel/`
- `SCAFFOLD.yaml` (134 KB) — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (99 KB) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (291 KB) — single key `scaffold_corner_design`

## Scaffold inventory (§1.1–§1.7)
- 14 entities, 8 state machines (Store, MenuVersion, Order × 3 parallel dimensions, DeliveryAssignment, Adjustment, RemittanceStatement), 3 `concurrency_rules` (Store publish, Order adjustment, Channel config), 9 calculations, 44 validations (single global priority ladder 1–44), 58 endpoints, 60 errors, 5 roles, `api_prefix: ""`.
- Roles: PlatformAdmin, StoreOperator (`entity_backed:Store`), ChannelPartner (`entity_backed:Channel`), CourierNetworkAgent (`entity_backed:CourierNetwork`), SettlementAnalyst; `role_model: segregation_of_duties` with SoD on adjustment reverse and statement settle.
- Mandatory logical clock `POST /_clock/set_current_utc` is the only `/_`-prefixed endpoint.

## Design instances
- §1.8: 9 rule_ids × 2 = **18 instances** (dual-variant divergence, nested rounding, circular tier base, parallel state dimensions, cyclic revision bound, cascade depth 5 / depth 3, priority-pair conflicts, boundary precision, empty-set, conditional precondition, half-open adjacency, resource temporal overlap, compensating reversal identity, conservation).
- §1.9: **88 instances** across all nine claim-extraction-guide sections — entities 10, state_machines 12, calculations 12, validations 16, endpoints 7, errors 16, rbac 7, complexity_layers 7, consistency_model 1. 19 of those are `excluded_because` stubs that cite a §1.8 instance by name (all citations verified to exist); 69 carry full `test_recipe`s.

## Audits
- **Error coverage: 60/60** error ids triggered or explicitly deferred to a named §1.8 instance.
- **Endpoint coverage: 58/58** endpoints exercised by at least one structured call (1110 calls scanned).
- **Name uniqueness** across the union of both design files: no duplicates. **Placeholder closure**: 0 unbound `${var}` in any `call` / `payload` / `as_user_id` / `assert` / `setup`. No non-schema keys on call objects.
- One scaffold change was needed to satisfy lint check (f): path id placeholders were normalized to the SKILL.md-documented `{id}` form (e.g. `/stores/{id}/hour-windows`), since check (f) matches sub-resource reverse-reachability against `/<parent>/{id}/<segment>` literally. Applied consistently across SCAFFOLD.yaml and both design files; no duplicate method+path resulted.

Lint verdict (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1110

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was listed, read, or grepped at any point.

## Step 3: Copy shared files — 2026-09-02T05:19:30.000Z

Copied `INSTRUCTION.md` to `tasks/task_2353_digital_ordering_middleware_delivery_channel/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T05:35:00.000Z

(Note: the first Step 4 subagent was terminated by an API error before writing any output; relaunched. Summary below is from the successful run.)

The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2353_digital_ordering_middleware_delivery_channel/workspace/PRD.md` — 479 lines.

**Sections covered**
- `## 1. Introduction` — 3 paragraphs (business framing, current-state pain, the two structural decisions: integer cents and the logical clock).
- `## 2. Global Behaviors` — 11 domain-derived subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim, byte-identical to `section-2.2-response-structure.md`); 2.3 Pagination and List Filtering; 2.4 The Logical Clock; 2.5 Common Resource Properties and Version Semantics; 2.6 Money, Basis Points and Rounding Discipline; 2.7 Optimistic Concurrency Control; 2.8 The Order in Which a Request Is Rejected (normative 44-step ladder); 2.9 Reference Resolution and Nested Paths; 2.10 Cascades, Derived Fields and Reconciliation; 2.11 Segregation of Duties on the Money Chain.
- `## 3. Business Requirements` — 9 freely-grouped workflow subsections: 3.1 Authoring the Single-Source Menu; 3.2 Bringing a Store Online and the Channel Pricing Ladder; 3.3 Channel Configuration and Availability Precedence; 3.4 86-ing, Restoring and Held Injections; 3.5 Capacity Buckets, Quotes and Order Intake; 3.6 POS Injection, Tablet Fallback, Readiness and Cancellation; 3.7 Dispatch, Courier Selection and the Handoff SLA; 3.8 Adjustments and the Review Loop; 3.9 Remittance Statements: Assignment, Reconciliation, Dispute and Settlement.
- `## 4. Endpoint Definitions` — intro paragraph on 201-vs-200 semantics plus a 58-row table, exactly 4 columns; every method/path/role set matches the scaffold.
- `## 5. Error Code Catalogue` — 61-row table, exactly 2 columns.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body: 57 required, 57 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- Status: PASS
```
(Also 0 missing across endpoint output-shape identifiers, all 60 error ids, all 5 role names, every state value and every enum value.)

```
Rule coverage check:
- state_machines[].transitions: 8 machines, all transitions expressed (incl. parallel injection/fulfillment/settlement dimensions)
- calculations[]: 9 of 9 expressed in operator-free prose, both quote variants (PROVISIONAL/CONFIRMED) and both settlement modes (GROSS_MODE/NET_MODE)
- validations[]: 44 of 44, rendered as the numbered §2.8 rejection ladder with error id + status + applies-to scope
- concurrency rules: 3 of 3, each with its expected_*_version field, error id and 412
- cross-entity side effects / cascades: all expressed
- field-level defaults: all walked and stated
- sibling-branch symmetry: preserved
- Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 841
- tokens starting with /: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS
```

Additional checks: no pseudocode operators or fuzzy quantifiers in §3; no bullet lists or schema tables in §3; no audit footer or write-sentinel left in the file.

**Three judgement calls worth flagging**
1. `ERR_ORDER_LINE_NOT_FOUND` is named in `validations[]` priority 4 but absent from `errors[]`. I included it in the §2.8 404 family and in §5 (hence 61 rows vs the scaffold's 60) rather than drop a scaffold-named rule.
2. Header naming: the skill mandates `X-User-ID`/`X-User-Role` while the scaffold says `X-Role`. §2.1 declares `X-User-Role` canonical and `X-Role` an accepted alias for the same value, so either convention passes. Scope headers (`X-Store-ID`, `X-Channel-ID`, `X-Courier-Network-ID`) are authoritative for entity-backed roles, with an explicit fallback to interpreting `X-User-ID` as the acting entity's `id` when the scope header is omitted.
3. The scaffold lists no `PAUSED → NORMAL` transition even though recompute-throttle's side effects assign the computed target. §3.5 specifies that the recompute assigns whichever target the derivation ladder produces, and enumerates the reachable pairs.

## Step 5: Generate unit tests — 2026-09-02T07:10:00.000Z

Test generation is complete and audited.

## Files written

`test_helpers/` (Stage 1, complete): `__init__.py` (barrel), `api_client.py` (one method per PRD endpoint + `api_client` singleton), `api_errors.py` (`ApiErrorId` + `HTTP_STATUS_CODES`), `test_users.py`, `factories.py`, `fixtures.py`, `assertions.py`, `constants.py`, `types.py`.

`test_suite/` (Stage 2): `conftest.py` plus 17 test modules — `test_01_quote_and_settlement_variants.py` … `test_09_money_and_slot_conservation.py` (queue A) and `test_10_resource_shapes_and_listings.py` … `test_17_concurrency_pagination_and_consistency.py` (queue B). All under `/home/ubuntu/github/CodingPRD/tasks/task_2353_digital_ordering_middleware_delivery_channel/`.

## Test counts

- **105 tests total**, 7,265 lines across both packages.
- **Queue A (Difficulty): 36 tests** — exactly 2 per each of the 18 non-stub §1.8 instances, one file per `rule_id`.
- **Queue B (Corner): 69 tests** — exactly 1 per each of the 69 non-stub §1.9 instances: entities 10, state_machines 9, calculations 8, validations 12, endpoints 6, errors 12, rbac 6, complexity_layers 5, consistency_model 1.

## Instances skipped

**Zero.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. The 19 `excluded_because:` stubs were deliberately never translated. No `skip`/`xfail`/placeholder anywhere.

## Audit results

- **Tag audit**: 105 tests, each docstring has exactly one `Design:` line and it is the last line. `DANGLING: []`, `STUB-TAGGED: []`, `UNCOVERED: []`, no Corner instance covered more than once, no Difficulty instance covered fewer than twice.
- **Error/status audit**: PRD §5 lists 61 errors; `ApiErrorId` has exactly 61 members with `HTTP_STATUS_CODES` matching the PRD table with zero mismatches. 51 distinct error ids are asserted across the suite; **zero** wrong `(ApiErrorId.X, N)` status pairs.
- **Import audit**: every name imported from `test_helpers` by every test module resolves (`MISSING: []`).
- **Hygiene**: no occurrence of "scaffold" in generated code; no `pytest.skip`/`skipif`/`xfail`/`@pytest.mark`/`unittest.mock`/`monkeypatch`; the only appearances of a section name are the five mandatory `Design: Corner/complexity_layers/...` citations. pyflakes-clean and `py_compile` OK on all files.
- Nothing was executed against a live server, and `workspace/implementation/` and all sibling task directories were never read.

## Design-yaml defects translated PRD-legally rather than verbatim

Each instance's core claim was PRD-covered, so I kept the test and asserted what the PRD actually derives:

1. `Order.order_state == NEW` — no such PRD field; asserted `fulfillment_status == "PREPARING"`.
2. `Order.open_adjustment_count` — that counter lives on `RemittanceStatement`; replaced with a filtered `GET /adjustments` `total_count`.
3. `delivery_fee_cents == 700` / `handoff_deadline_at == 16:15` on an **OFFERED** assignment — PRD line 296 makes both 0/null until acceptance; asserted 0 / `None` (two instances).
4. `occ_adjustment_with_consumed_order_version_returns_412` assumed an AUTO_ACCEPT channel accepts on *creation*; the PRD accepts on *submission*, so the test creates (DRAFT), proves the token is consumed, then submits.
5. `lateness_seconds` / `penalty_cents` / `handed_off_at` rendered as the PRD's `handoff_lateness_seconds` / `handoff_penalty_cents` / `handoff_at`.
6. A channel-listing assertion keyed on `menu_version_id` (not a listing field) was re-keyed on `menu_item_id`.

One real bug was caught during review: a statement-dispute call was being made with SettlementAnalyst headers, but the PRD restricts `POST /remittance-statements/{id}/dispute` to ChannelPartner, and `ERR_UNAUTHORIZED` (ladder rank 2) would have outranked the expected `ERR_INVALID_STATEMENT_STATE` (rank 39); fixed to channel-partner headers.

## Step 6: Generate implementation — 2026-09-02T07:10:00.000Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/` (3,306 lines of Python across 24 modules):

**Entry / infrastructure**
- `app.py` — Flask app factory, blueprint registration, `ApiError` handler, 404/405/400/500 fallbacks, `PORT` env (default 10000)
- `start.sh` (executable) — installs Flask only if missing, `exec python3 app.py`
- `requirements.txt` — `Flask>=3.0`
- `clock.py` — logical clock, default `2026-08-01T00:00:00Z`, ISO8601 with exactly 3 fractional digits, tz-offset local-time helpers
- `db.py` — 14 in-memory dicts, ID/sequence generators, `record(journal=)`, request-idempotent `touch()`, `sorted_records()` (created_at asc, insertion-order tie-break)
- `errors.py` — every error ID as a constant plus the complete ID→HTTP-status map
- `response.py` — envelope builders (`req_` + 20 uppercase alphanumerics), `paginate()`
- `middleware.py` — role gate decorator, scope resolution from `X-Store-ID`/`X-Channel-ID`/`X-Courier-Network-ID` with `X-User-ID` fallback
- `validation.py` — typed body/query extractors, bool-rejecting int parsing, pagination bounds

**Services** — `services/constants.py` (enums + every tuned constant), `money.py` (`Decimal` ROUND_HALF_UP, bps), `domain.py` (pricing, availability derivation, throttle, 15-min buckets, quotes, order totals, courier selection + occupancy, penalty ladder, settlement figures/tiers, cascades), `serializers.py` (per-entity field projection; journal types emit only `id`/`created_at`)

**Routes** (11 blueprints) — `common.py` (existence lookups), `clock_routes.py`, `stores.py`, `channels.py`, `menu_versions.py`, `listings.py`, `availability.py`, `orders.py`, `networks.py`, `assignments.py`, `adjustments.py`, `statements.py`

## Endpoint count
58 method+path pairs registered (57 domain endpoints + `POST /_clock/set_current_utc`), matching the PRD §4 table exactly. Flask's built-in `/static/<path>` is the only extra rule. `GET /channels` and `GET /menu-versions` correctly return 405 since the PRD defines no list endpoints for them.

## Constraints honored
- Storage is module-level Python dicts only. No SQLite, no file writes, no `/tmp` cache, no `open()` anywhere in the package.
- Zero seeding: on a fresh boot every list endpoint returns `total_count: 0` (verified for stores, channel-listings, availability-events, orders, delivery-assignments, adjustments, remittance-statements). The clock also resets to `2026-08-01T00:00:00Z` on every boot, so `--isolation per-test-server` gets a pristine world each test.

## Verification
Booted fresh via `start.sh` three times on separate ports; each answered immediately. Trivial request `GET /stores` returns 200 with a well-formed envelope (`api_request_id` matching `req_[A-Z0-9]{20}`, timestamp with 3 fractional digits, `limit`/`offset`/`total_count`/`has_more` present); unauthenticated request returns 401 `ERR_UNAUTHENTICATED`; unknown path returns 404.

Two end-to-end smoke suites (~113 assertions total, both `ALL PASS`) exercised: NICKEL/CENT pricing and per-line tax rounding, money identity `channel_collected == brand_net + commission + service_fee + refunded_total` (before and after refunds), quote padding (base + 2/order load + 8 throttle + 11 courier travel), bucket capacity rejection, throttle NORMAL/THROTTLED/PAUSED with `SUPPRESS_ON_THROTTLE` vs `IGNORE_THROTTLE`, 86-ing propagation with `HONOR_86`/`IGNORE_86` counts and PENDING-order holds plus slot release, resume-injection gates, POS retry → tablet fallback → terminal failure, courier selection by priority skipping inactive networks, occupancy/capacity, handoff lateness with the 0/150/400/900 penalty ladder, delivery, adjustment review loop (AUTO_ACCEPT, revision rounds with the 2-round limit, accept, reverse with exact money undo), OCC 412s on all three endpoints, SoD on reverse and settle, and the full statement cycle including dispute unwind (aggregates zeroed, orders released, reassignable) and tier/rebate computation.

## Step 7: Run tests and iterate — 2026-09-02T09:14:00.000Z

Summary

**Iterations run:** 1 diagnostic pass over the pre-existing failure union, then 5 full 8-round parallel sweeps (40 rounds total) after the fix batch.

**Result:** the union of *real* (assertion/domain) failures is now empty. Sweep A after the fixes: rounds 2,3,5,6,7,8 = 105/105, rounds 1 and 4 each lost exactly one test. Sweep B: rounds 2,3,4,6,7,8 = 105/105, rounds 1 and 5 each lost exactly one test. Sweeps C-E ran while the host was saturated (load 130 → 250, 240-358 concurrent `prd-bench-local-run` processes from other pipelines) and produced 173-283 non-passes with **zero** real failures. Every single non-pass in all 40 rounds was `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:PORT -sTCP:LISTEN ...)' timed out after 5 seconds"` (plus 2 `Connection broken`/`RemoteDisconnected`) — the runner's own hardcoded 5s port-kill timeout in per-test-server teardown, hitting a different arbitrary test each round, never the same test twice. This is the known host-contention signature, not an artifact defect. I waited for a quieter window three times; load only climbed, so a literally green 8/8 sweep was not reachable on this host.

**Tests deleted:** none. Every failing assertion turned out to be either PRD-derivable (implementation fix) or a fixture/setup inconsistency (test fix).

**Fixes applied to `test_helpers/`:** none — the failures traced to per-test setup in the test files, not to shared fixtures.

**Fixes applied to `test_suite/`:**
- `test_suite/test_12_calculations.py::test_the_posture_ladder_trips_exactly_at_capacity_and_at_double_capacity` — setup used the default MARKETPLACE channel, whose `throttle_policy` is `SUPPRESS_ON_THROTTLE`; once the ladder reached `THROTTLED`, PRD §3.3/§3.4 correctly turned the shelf `THROTTLE_SUPPRESSED`, so the second `place_order` was rightly refused with `ERR_ITEM_NOT_AVAILABLE`. Switched the setup to an `IGNORE_THROTTLE` (aggregator) channel so the test exercises the posture ladder it cites instead of the availability ladder. TEST BUG, fix makes it more PRD-faithful.
- `test_suite/test_17_concurrency_pagination_and_consistency.py::test_two_roles_contend_for_one_channel_token_and_the_shelf_keeps_its_price` — hardcoded `expected_channel_version=1` after a publish, but publishing recomputes the channel's `listing_count`, and PRD §2.10 says a derived-field write is a mutation that increments `version`. Now reads the post-publish token (asserting it is 2, which PRD determines) and rebases the three version assertions on it. TEST BUG.
- `test_suite/test_17_concurrency_pagination_and_consistency.py::test_three_derived_counters_come_back_down_as_well_as_up` — replayed the store version observed right after the first publish, but the intervening order create and cancel each wrote the store's counters (`open_order_count`, `reserved_prep_slots`) and therefore moved `version`. Now asserts the version has moved and lets the helper re-read it, exactly as PRD §2.10 instructs clients to do. TEST BUG.

**Fixes applied to `implementation/`** (both in `workspace/implementation/services/domain.py`):
- New `open_assignment_count(network_id)` + `recompute_network_open_assignments` — `CourierNetwork.open_assignment_count` now counts assignments whose `state` is `OFFERED` or `ACCEPTED`, instead of the network's occupancy count at the current clock. PRD §2.8 rank 29 defines an *open* assignment as one "in `OFFERED` or `ACCEPTED`", PRD keeps "occupancy count" as a separate, explicitly defined clock-dependent notion (§3.7), and §2.10's "derived counters are maintained, not recomputed on read" plus §2.2's inert clock make a clock-dependent stored counter impossible to maintain. Fixes `test_08_temporal_overlap.py::test_a_network_is_still_occupied_at_the_closing_instant_of_its_interval` and `test_15_error_catalogue.py::test_capacity_is_judged_again_at_acceptance_not_only_at_dispatch`.
- `_quote_load_count` — the CONFIRMED replay cut-off changed from `created_at < before` to `created_at <= before`. The new order is not yet in storage when its quote is computed, so every remaining order carrying a timestamp at or before the cut-off was in fact "created strictly before the new order" (§3.4); the strict form silently dropped same-instant siblings under the frozen logical clock, while the `<=` form still honours the chronological-replay intent when the clock has been moved backwards. Fixes `test_13_intake_and_publish_validations.py::test_one_undeliverable_item_sinks_the_whole_delivery_basket` (16:25 vs 16:23 — one missing 2-minute load pad) and leaves every other pinned `promised_ready_at` unchanged (verified against all 12 such assertions in the suite).

No endpoint, field, side effect or seeded data was added; storage remains in-memory dicts only. Transient `results.*.json` sweep files were removed at the end.

**Orchestrator note:** because Step 7 exited without a literally green 8/8 sweep, the orchestrator launched an independent lower-concurrency (3-round) verification sweep to confirm the residual non-passes are the runner's own `lsof -ti:PORT` 5s teardown timeout under host contention (load average 240, 389 concurrent `prd-bench-local-run` processes from other pipelines on a 32-core host) rather than artifact defects. Result recorded below.

## Step 8: Finalize PRD — 2026-09-02T09:25:00.000Z

Done.

## Line counts
- `PRD.md`: 478 lines / 13,406 words / 95,157 bytes
- `PRD_FINALIZED.md`: 478 lines / 13,510 words / 95,799 bytes
- Delta: **0 lines (0.0%)**; 2 of 478 lines revised in place (+104 words, +0.7% words)

## Changes

- **§3.7 (line 290)** — insert — added an invariant for `CourierNetwork.open_assignment_count`: a maintained counter equal to the number of that network's assignments in `OFFERED` or `ACCEPTED`, counted without reference to occupancy intervals or the current clock, and explicitly distinguished from the clock-dependent occupancy count defined in the next paragraph — `workspace/implementation/services/domain.py:206-225`
- **§3.5 (line 262)** — revise — the `CONFIRMED` quote replay cut-off changed from "created **strictly before** the new order's own `created_at`" to "`created_at` **at or before** the new order's own `created_at`", with the rationale that the new order is not yet stored, plus a note that the only orders excluded are those stamped strictly later (reachable only after a backward clock move) — `workspace/implementation/services/domain.py:129-145` (with `before=created_at` supplied at `workspace/implementation/routes/orders.py:75-76`)

No PRD edit for the three `test_suite/` fixes: all three are fixture/setup bugs whose expected behavior PRD already determines (§3.3/§3.5 availability ladder for the `test_12` throttle case; §2.10's "a derived-field write is a mutation … increments its `version`" for both `test_17` version-rebase cases). Prose kept verbatim there.

## Per-edit pre-edit search log

**Edit 1 — subject: `CourierNetwork.open_assignment_count` (definition + every write site)**

(b) Paths enumerated (grepped `open_assignment_count|recompute_network_open_assignments|occupancy_count` across `implementation/`, then read each hit):
- `services/domain.py:191` `occupancy_count` (clock-dependent, closed interval, `exclude_assignment_id`) — the *other* notion; confirmed the new sentence keeps them separate rather than conflating them.
- `services/domain.py:206` `open_assignment_count`, `:219` `recompute_network_open_assignments` (touches only when the value moves).
- `services/domain.py:237` `select_courier_network` — eligibility uses `occupancy_count`, **not** the counter; confirmed the new sentence makes no claim about selection.
- `services/domain.py:259` `withdraw_open_assignments` → recompute per assignment's own network (count drops).
- `routes/orders.py:330-371` dispatch — creates `OFFERED`, then recompute (count +1).
- `routes/assignments.py:71-85` accept — `occupancy_count(exclude=self)` gate, then `OFFERED→ACCEPTED` + recompute (**no change**, since both states are open; invariant holds, no version bump).
- `routes/assignments.py:100-104` decline — `→DECLINED` + recompute (−1).
- `routes/assignments.py:126-138` handoff — `→HANDED_OFF` + recompute (−1); PRD never mentioned a recompute here, so the "always equals" invariant is what pins it.
- `routes/assignments.py:158-165` deliver — `HANDED_OFF→DELIVERED`, **no** recompute; count is unchanged either way, so the invariant still holds.
- `routes/networks.py:34-49` create — seeds 0, no assignments exist; also confirmed there is **no** network PATCH/deactivate endpoint that could shift the counter.
- `services/serializers.py:198` — the field is echoed straight from storage (consistent with "maintained, not recomputed on read").
- PRD-side sweep: lines 161 (rank 29), 188 (§2.10), 290/296/300 (§3.7); §4 and §5 have no mention.

(c) Wording adjustment: dropped a planned trailing clause "and moving the clock never changes it" as redundant with §2.4's inert-clock rule, and phrased the distinction as "not the same figure as the clock-dependent occupancy count defined below" rather than any claim about eligibility or selection — selection genuinely uses the clock-dependent count, so a broader claim would have created a new mismatch at `domain.py:237` and `assignments.py:71`.

**Edit 2 — subject: the `CONFIRMED` quote's chronological-replay cut-off**

(b) Paths enumerated (grepped `compute_quote|_quote_load_count|before=`, plus `QUOTE_INJECTION_STATUSES`):
- `services/domain.py:129-145` `_quote_load_count` — the sole cut-off site (`created_at <= before`), plus the `injection_status ∈ QUOTE_INJECTION_STATUSES` / `fulfillment_status == "PREPARING"` filters.
- `services/domain.py:148-166` `compute_quote` — shared by both variants; pad/travel/total arithmetic untouched.
- `routes/orders.py:74-78` CONFIRMED caller: `at=created_at, before=created_at` (same instant for both), then the `>90` refusal, then `promised_ready_at` pinned once at `:98` and never rewritten anywhere else in `orders.py`.
- `routes/stores.py:272` PROVISIONAL caller: `before` omitted → no time filter at all; confirmed the edit is scoped to the CONFIRMED sentence and leaves line 260's "evaluated at request time" untouched.
- `services/constants.py:65` `QUOTE_INJECTION_STATUSES` — matches PRD's stated qualifying set, so "qualifying orders" needed no redefinition.
- Also checked the neighbouring `bucket_load` population (`domain.py:95`, `BUCKET_INJECTION_STATUSES`) to be sure the edit's "qualifying" wording could not be misread onto the bucket rule — it is a separate, differently-populated count and the sentence stays inside the quote paragraph.

(c) Wording adjustment: kept the sentence's "chronological replay" framing and the "`throttle_state` as of that same instant" clause verbatim, changing only the comparison, and added the exclusion direction ("only excludes orders stamped strictly later than the new one, possible only after a backward clock move") so the sentence does not read as "all stored orders count" — which would mis-describe the `not (created_at <= before)` branch. Final phrasing grammar-cleaned in a second pass.

### Step 7 verification (orchestrator, 2026-09-02T09:44Z)

Independent single-round sweep (`--isolation per-test-server`, concurrency 1 to minimise footprint) on `test_suite/` + `workspace/implementation/`:

```
total: 105   passed: 48   failed: 0   errors: 57
```

All 57 non-passes carry the identical `error_message`:

```
failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:36323 -sTCP:LISTEN 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; true' timed out after 5 seconds"
```

each with `duration_seconds ≈ 5.02` — i.e. the runner's own hardcoded 5-second port-kill timeout in per-test-server teardown, not the artifact. **`failed: 0` — zero assertion failures.** Host state during the run: load average 339, 118–183 concurrent `prd-bench-local-run` port-registry holders from other pipelines on a 32-core box, with one observed OS `Killed` of a Flask child. This confirms Step 7's diagnosis: the union of real (assertion/domain) failures is empty, and a literally green 8/8 sweep is not reachable on this host while it is this saturated.

## Step 9: Complete PRD — 2026-09-02T09:45:00.000Z

Report complete — final measurement and change list below.

## Deliverable

`workspace/PRD_COMPLETED.md`

- Source `PRD_FINALIZED.md`: **478 lines / 95,799 chars**
- Completed `PRD_COMPLETED.md`: **478 lines / 103,432 chars** (**char delta +7,590**)
- Line count unchanged: every change is an in-paragraph insert or revision — **33 modified lines across 32 diff hunks, 0 lines added, 0 new sections, 0 implementation files touched**.
- Classification: **23 ambiguity-pins**, **10 mismatch-revisions**.

## Changes

- §2.1 — insert — ambiguity — a role or user header present but blank counts as omitted (`ERR_UNAUTHENTICATED`) — `middleware.py:56-63`
- §2.1 — insert — ambiguity — a blank scope header also falls back to `X-User-ID`; top-level collections apply no implicit scope filter and never return `ERR_FORBIDDEN_SCOPE`, while nested collections scope-check the parent — `middleware.py:38`, `routes/stores.py`, `routes/orders.py`
- §2.3 — insert — ambiguity — `limit`/`offset` must be base-10 integers or `ERR_INVALID_REQUEST`; `offset ≥ total_count` yields an empty page — `validation.py:146,187`, `response.py:56-64`
- §2.3 — insert — ambiguity — equal `created_at` values are broken by insertion order — `db.py:77`
- §2.3 — insert — ambiguity — exhaustive per-collection filter parameter names; unknown query parameters ignored — `routes/*.py` list handlers
- §2.4 — revise — mismatch — wall clock is never read *except* for the envelope's `api_request_timestamp` — `response.py:15,26`
- §2.5 — insert — ambiguity — one request moves a record's `version` by at most 1 and stamps a single `updated_at` — `db.py` `touch()`
- §2.8 r26 — insert — ambiguity — `ERR_INVALID_ORDER_STATE` also fires on cancel when `settlement_status` is no longer `SETTLEABLE` — `routes/orders.py:306`
- §2.8 r27 — insert — ambiguity — `ERR_ORDER_NOT_INJECTED` also applies to assignment acceptance — `routes/assignments.py:70`
- §2.8 r31 — insert — ambiguity — `ERR_INVALID_ASSIGNMENT_STATE` also fires when the network's `is_active` is false at acceptance — `routes/assignments.py:67-68`
- §3.2 — insert — ambiguity — all four `PATCH /stores` fields optional; an empty patch still bumps `version` — `routes/stores.py:87-90`
- §3.2 — revise — mismatch — publish deletes every listing the store holds (whichever version built it), derives the rebuilt `availability_state` through the full ladder, skips both `published_store_count` movements on same-version republish, builds item-major/channel-minor in registration order; precondition is `PUBLISHED` **or** `EXHAUSTED` — `routes/stores.py:170,185,220-226`
- §3.2 — revise — mismatch — *any* successful publish lifts `PAUSED` to `NORMAL` (not only the first); `THROTTLED` is unaffected — `routes/stores.py:189`
- §3.3 — insert — ambiguity — only `expected_channel_version` is required on `PATCH /channels`; empty patch still bumps `version` — `routes/channels.py:72-82,103`
- §3.3 — insert — ambiguity — `suppressed` is a required boolean and every write bumps `version`, even restating the same flag — `routes/listings.py:57,63`
- §3.4 — revise — mismatch — `menu_item_id` must belong to the store's *active* version (`ERR_MENU_ITEM_NOT_FOUND`, checked after the unpublished gate); `actor_channel_id` must resolve, be the caller's own, and is recorded verbatim, never inferred; events are scoped by `store_id` alone — `routes/availability.py:25-40,87`
- §3.4 — insert — ambiguity — a `HONOR_86` listing already at the target flag counts in neither `propagated_listing_count` nor `skipped_listing_count` — `routes/availability.py:43-54`
- §3.4 — revise — mismatch — the bubble inspects every listing of the version's items at every store; a version with no items or no listings never bubbles — `services/domain.py:392-409`
- §3.5 — insert — ambiguity — `channel_id`/`fulfillment_mode` are required query params validated first (`ERR_INVALID_REQUEST`), then `ERR_CHANNEL_NOT_FOUND`, then scope — `routes/orders.py:146`
- §3.5 — insert — ambiguity — lines are stored in the request array's order, which is the `GET /orders/{id}/lines` order — `services/domain.py:375-378`
- §3.6 — insert — ambiguity — the attempt record carries the reported `pos_result_code` verbatim — `routes/orders.py:192,208`
- §3.6 — revise — mismatch — the threshold ladder applies only from `PENDING`; a non-OK result from `TABLET_FALLBACK` only records the attempt and increments the count — `routes/orders.py:217-223`
- §3.6 — revise — mismatch — cancel takes a required `reason_code`, and a non-`SETTLEABLE` `settlement_status` is refused with `ERR_INVALID_ORDER_STATE` — `routes/orders.py:300,306`
- §3.7 — insert — ambiguity — registration order settles same-instant `created_at` in courier selection — `services/domain.py:242-248`
- §3.7 — revise — mismatch — acceptance checks run state → inactive network (`ERR_INVALID_ASSIGNMENT_STATE`) → `ERR_ORDER_NOT_INJECTED` → occupancy — `routes/assignments.py:65-73`
- §3.8 — revise — mismatch — submit repeats neither the already-settled nor the refund-ceiling check — `routes/adjustments.py:133-136`
- §3.8 — insert — ambiguity — `note` on request-revision is accepted as an optional string but neither stored nor echoed — `routes/adjustments.py:158`
- §3.8 — insert — ambiguity — a reversal keeps its `remittance_statement_id` but stops feeding `adjustment_total_cents` — `routes/adjustments.py:221-239`, `services/domain.py:291-293`
- §3.9 — insert — ambiguity — `order_ids` is a required non-empty string array (empty → `ERR_INVALID_REQUEST`) and the three eligibility tests are applied order by order in array order, ahead of the settlement-status sweep — `routes/statements.py:83,90-99`
- §3.9 — insert — ambiguity — the pipeline also restates `order_count` — `services/domain.py:343-354`
- §3.9 — insert — ambiguity — dispute takes a required `reason_code` and also resets `open_adjustment_count` to 0 — `routes/statements.py:162,187`
- §4 — revise — mismatch — `GET /courier-networks/{id}` returns the *maintained* `open_assignment_count`, not live occupancy — `services/domain.py:206-216`

Deliberately left alone (judged not worth prose): the unrouted-path `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_HTTP_ERROR` fallbacks in `app.py:44-61`, and one unreachable-in-practice case where `refresh_listing_availability` corrects a listing's `availability_state` without a version bump (`services/domain.py:38-47`) reachable only via a `PATCH /channels` throttle-policy change that does not cascade.

## Step 7 verification, continued — 2026-09-02T11:25:00.000Z

Because Step 7 exited without a literally green 8/8 sweep, the orchestrator ran further low-concurrency verification rounds. Results (all against the final `test_suite/` + `workspace/implementation/`):

| round | passed | failed (assertions) | errors (infrastructure) |
|---|---|---|---|
| `verify.solo.json` (full suite) | 48 | **0** | 57 — all `lsof -ti:PORT` 5s teardown timeout |
| `verify.solo2.json` (full suite) | 90 | **0** | 15 — all `lsof` teardown timeout |
| `verify.solo3.json` (full suite) | 54 | 1 — `RemoteDisconnected` (server OS-killed mid-request) | 50 — all `lsof` teardown timeout |
| `/tmp/subset.json` (4-module subset, 34 tests) | 19 | **0** | 15 — `lsof` teardown timeout |
| `verify.subset.json` (same subset, after the runner fix below) | 33 | **0** | 1 — pytest-timeout on server boot |

**Union across all rounds: 105 distinct tests seen, 105 passed at least once, 0 never-passing. Zero assertion failures in any round.** Every non-pass in every round was one of three infrastructure signatures: the runner's own hardcoded 5-second `lsof -ti:PORT -sTCP:LISTEN` port-kill timeout in per-test-server teardown, an OS `Killed` of the Flask child under memory pressure, or a pytest-timeout waiting for a boot that the loaded host could not deliver in 30s. None repeated on the same test.

**Independent confirmation of the root cause:** at 10:42–10:54 UTC another process on this host edited the shared runner's `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py` to make the port kill best-effort (`from .port_utils import kill_port`, wrapped so its lsof probe timing out no longer errors the test). The runner is installed editable, so my in-flight subset run briefly failed 34/34 with `NameError: name 'kill_port' is not defined` while the edit was half-applied; once it landed, the same subset went from 15 teardown errors to 1 unrelated boot timeout. That is external confirmation that the residual non-passes were the runner's teardown probe, not this task's artifact. I did not modify that file — it is another party's in-flight work.

**Why no green 8/8 sweep is recorded:** host load average climbed from 213 at the start of Step 7 to **10,543** by 11:25 UTC on a 32-core box (other pipelines, not this one — my own 4 remaining runners were killed at 11:24 to stop contributing). A final 4-round sweep launched at 11:09 was terminated before any `results.N.json` was written. `results.{1..8}.json` are therefore **absent** from `workspace/implementation/`; the `verify.*.json` files above are retained in their place as the durable evidence, and this deviation from the skill's output spec is recorded here deliberately rather than papered over.

**Bottom line:** the artifact is clean — 105/105 tests confirmed passing, 0 assertion failures, no test deleted, no assertion weakened. What is missing is a single simultaneous green sweep, which this host's saturation prevented.

## Pipeline complete — 2026-09-02T11:25:00.000Z

Deliverables present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 17 modules, 105 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (24 modules + `start.sh`).
