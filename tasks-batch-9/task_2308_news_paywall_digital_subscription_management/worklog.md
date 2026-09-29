# Worklog — task_2308_news_paywall_digital_subscription_management

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2308_news_paywall_digital_subscription_management/` and `workspace/` subdirectory (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T17:15:09.923Z

Done. All three scaffold artifacts are generated and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2308_news_paywall_digital_subscription_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2308_news_paywall_digital_subscription_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2308_news_paywall_digital_subscription_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  844

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2308_news_paywall_digital_subscription_management/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, 137 KB) — top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`; neither design key is present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single key `scaffold_difficulty_design`).
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single key `scaffold_corner_design`).

§1.0–§1.7 contents (`api_prefix: /paywall`, scenario text used verbatim):
- 13 entities (OfferPlan, PaywallRule, Article, Reader, Subscription, Invoice, PaymentAttempt, CancellationRequest, SaveOffer, Hold, GroupAccount, Seat, ReaderEvent); graph topology.
- 9 state machines, including the 3-dimensional Subscription (lifecycle × dunning × print_fulfillment), plus 2 optimistic-concurrency rules (`subscription-create-stale-plan`, `seat-assign-stale-group`).
- 11 calculation rules (meter allowance with override/band/floor, paywall-rule specificity selection, cycle base price with intro/step-up/grandfathering + dual `preview_quote`/`billed` variants, invoice total assembly with seat lines and hold credits, hold credit rate, dunning retry schedule with card-updater extension, engagement score with rolling-30d vs cohort-normalized variants, churn/propensity banding, seat concurrency admission).
- 58 validation rules in one global priority chain; 48 endpoints; 55 errors; 5 roles (Reader, GroupAdmin, SubscriptionOpsAgent, RevenueManager, ComplianceOfficer) with an entity-backed ownership rule and a segregation-of-duties rule on the price-increase pipeline.

§1.8: 9 rule_ids / 22 instances — dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (3), cross_entity_state_dependency (3), resource_temporal_overlap (2), compensating_invariant (2).

§1.9: 9 sections / 96 instances (71 full test recipes + 25 `excluded_because` stubs pointing at named §1.8 instances) — entities 12, state_machines 14, calculations 12, validations 23, endpoints 7, errors 16, rbac 4, cross_cutting_complexity_layers 6, consistency_model 2.

Verified beyond the linter: instance names unique across both design files; all 25 stubs resolve to real `rule_id / name` pairs and carry no `test_recipe`; zero unbound `${...}` placeholders across all 93 recipes; every one of the 55 catalog errors is referenced by at least one design instance.

One SCAFFOLD.yaml correction was needed during the §1.9 audit: `ERR_DUNNING_EXHAUSTED` was unreachable because the terminal-lifecycle rule (priority 24) and the invoice-status rule shadowed it after any final decline. Fixed by narrowing priority 24's `applies_to` to holds and cancellation-requests and swapping priorities 26/27 so the dunning-episode check precedes the invoice-status check (catalog entries reordered to match); `errors / payment_attempt_after_final_decline_rejected` now asserts that path.

## Step 3: Copy shared files — 2026-09-01T17:15:09.923Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T17:31:00.000Z

All three Hard Contracts pass. The 14 flagged identifiers are internal scaffold names only — calculation names (`invoice_total_assembly`, `paywall_access_decision`, `dunning_retry_schedule`, etc.), variant labels (`preview_quote`/`billed_amount`, `rolling_30d`/`cohort_normalized`) and the helper `clock_date` — none of which are persisted fields or wire identifiers; all are rendered as prose descriptions per spec. No actual field name is unexpressed.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2308_news_paywall_digital_subscription_management/workspace/PRD.md` — **463 lines**, 5 top-level sections, 21 subsections, ending at §5 with no audit footer.

**Structure:** §1 Introduction (3 paras) · §2 Global Specifications (12 subsections: RBAC, verbatim response structure, pagination/filters, logical clock, common properties, rounding discipline, stale-view guards, validation precedence, nested path resolution, parallel state dimensions, interval geometry, billing run) · §3 Business Logic (9 domain-grouped workflows: plan authoring/price ladder, regulated price-increase pipeline, paywall rules & access decision, engagement/churn/interventions, subscription opening & cycle billing, dunning & card updater, service holds, cancellation & save offers, institutional seats) · §4 endpoint table (4 columns) · §5 error catalogue (2 columns).

## Coverage audit

| Scaffold element | Count | Covered |
|---|---|---|
| Entities | 13 | 13 |
| Entity fields | 145 | 145 |
| State-machine blocks / transitions | 9 / 42 | 9 / 42 |
| Calculations (incl. 2 dual-variant pairs) | 11 | 11 |
| Validations | 58 | 58 |
| Endpoints | 48 (25 POST, 23 GET) | 48, roles verified 0 mismatches |
| Endpoint inputs (body + query) | 120 | 120 |
| Errors | 55 | 55, statuses verified 0 mismatches |
| Roles | 5 | 5, each with identity prose |
| Concurrency rules | 2 | 2 |

## Contract reports

```
Field coverage check (2 independent passes: tokenized + strict exact-backtick):
- entities[].fields: 145 required, 145 present, 0 missing
- endpoints[].input (request_body + query_params): 120 required, 120 present, 0 missing
- composite output fields (billing-run report, clock): 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 58 checked, 58 expressed in prose (full precedence ladder in §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 42 checked, 42 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (all constants incl. composite maps PROPENSITY_ALLOWANCE_DELTA, EVENT_WEIGHTS, DUNNING_RETRY_OFFSET_DAYS decomposed into prose), 0 missing
- validations[] conditions: 58 checked, 58 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 25 checked, 25 expressed, 0 missing
- entities[].fields[] structured content: 145 checked, 145 reconstructible from prose, 0 missing
- sibling-branch symmetry: 4 groups checked (preview_quote/billed_amount, rolling_30d/cohort_normalized, accept/decline save-offer branches, COMPLETED/RELEASED hold exits), 4 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1114
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- tokens containing any slash: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; zero pseudocode operators (`>=`, `<=`, `+=`, `min(`, `max(`, `round_half_up(`, `==`, `!=`, `IN {`); zero fuzzy hedges; OCC framed purely as stale-version (no "simultaneously"/"race"/"first-writer-wins" concurrency framing); skeleton avoids the example PRD's anti-patterns (12 §2 subsections with domain-specific titles, 9 §3 groupings).

**One scaffold discrepancy handled:** `SaveOffer.pause_days` declares a field range of 1–90 while validation priority 39 (`ERR_SAVE_OFFER_DISCOUNT_CAP`) enforces 7–90. §3.8 states the enforced rule (7 to 90 inclusive), since that is what the endpoint actually rejects on.

**Read restrictions honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T18:50:00.000Z

The suite is complete. Final state:

## Files written

**Infrastructure** — `/home/ubuntu/github/CodingPRD/tasks/task_2308_news_paywall_digital_subscription_management/test_helpers/` (8 modules + `__init__.py` barrel: `types`, `api_client`, `api_errors`, `constants`, `test_users`, `factories`, `assertions`, `fixtures`).

**Tests** — `/home/ubuntu/github/CodingPRD/tasks/task_2308_news_paywall_digital_subscription_management/test_suite/`, `conftest.py` + 20 test modules, **120 tests**:

| queue | files | tests |
|---|---|---|
| A (§1.8 difficulty) | `test_01` … `test_08` | 49 |
| B (§1.9 corner) | `test_09` … `test_20` | 71 |

Files added in this final stretch: `test_18_not_found_precedence_and_flow_state_conflicts.py` (5), `test_19_closed_episodes_closed_flows_and_role_boundaries.py` (8 — the four remaining `errors` instances plus all four `rbac` instances), `test_20_optimistic_concurrency_and_visibility_of_effects.py` (5 — 3 `cross_cutting_complexity_layers` + 2 `consistency_model`).

## Audit results (both mandatory passes green)

- **Coverage**: all 22 non-stub difficulty instances have ≥2 tests; all **71** non-stub corner instances have exactly one test each (entities 12, state_machines 12, calculations 6, validations 18, endpoints 5, errors 9, rbac 4, cross_cutting 3, consistency_model 2). Every file has ≥5 tests.
- **Scaffold-citation pass**: exactly one `Design:` line per test, always the last docstring line; zero dangling tags, zero tags pointing at any of the 25 `excluded_because:` stubs.
- **PRD-citation pass**: 254 `PRD: "…"` quotes, all verbatim single-line matches against `workspace/PRD.md` (0 misses). No `skip`/`skipif`/`xfail` anywhere. `compileall` and pyflakes clean; every barrel symbol imported by the suite verified to exist.

## Instances skipped

None beyond the 25 pre-declared `excluded_because:` stubs (which are covered by their named difficulty counterparts). No instance failed the PRD-first filter outright, but three design claims were adjudicated against the PRD and narrowed rather than asserted as written:

- `price_change_apply_updates_standard_price_and_clears_pending` — the design's "pending fields cleared" contradicts the billed-variant proration rule that still reads `pending_effective_on` while `APPLIED`; the test asserts only `price_change_state == "APPLIED"` and `standard_price_cents == 1799`.
- `reader_cannot_open_a_subscription_or_run_the_batch_denied` — the design's `active_subscription_count == 0` contradicts PRD line 258 (creation recomputes the count including `PENDING_ACTIVATION`); that assertion was dropped.
- `holds_and_cancellations_shared_but_scoped_to_the_owning_reader` — the design's `initiated_on` field does not exist in the PRD; the test asserts `status == "INITIATED"`, `save_offer_count == 0`, `retained is False` instead.

Also worth flagging for the implementation side: `clock_moving_backwards_rejected` had to verify clock retention indirectly (re-set to the identical value, then assert a fresh reader's `meter_period_started_on`), because §4 exposes no GET-clock endpoint and the PRD never names a field in the set-clock response body.

## Step 6: Generate implementation — 2026-09-01T19:50:00.000Z

Implementation complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2308_news_paywall_digital_subscription_management/workspace/implementation/`)

**Foundation (flat modules):** `app.py`, `config.py`, `errors.py`, `clock.py`, `db.py`, `response.py`, `validation.py`, `middleware.py`, `serializers.py`, `lookup.py`, `requirements.txt`, `start.sh`.

**`routes/`** (12 blueprints, all registered under `/paywall`): `offer_plans.py`, `paywall_rules.py`, `articles.py`, `readers.py`, `access_decisions.py`, `subscriptions.py`, `holds.py`, `invoices.py`, `cancellations.py`, `group_accounts.py` (group accounts + seats), `billing_runs.py`, `clock_control.py`.

**`services/`** (12 modules): `money.py`, `pricing.py`, `engagement.py`, `paywall.py`, `entitlement.py`, `events.py`, `derive.py`, `holds.py`, `dunning.py`, `cancellation.py`, `seats.py`, `billing_run.py`.

## Endpoint count
`app.url_map` reports exactly **48 endpoints — 25 POST / 23 GET**, matching the SCAFFOLD inventory one-for-one.

## Structure
- **State machines:** each parallel dimension is an independent field mutated only by its own transition helper — Subscription `lifecycle_status` × `dunning_status` × `print_fulfillment_status`, OfferPlan `status` × `price_change_state`. Multi-hop cascades live in one place each: 4-hop confirm-cancellation (`services/cancellation.confirm`), 5-hop final decline (`services/dunning.record_attempt`), 3-hop price-increase apply (`routes/offer_plans.py`), and the five nightly passes pinned as HOLDS → EXPIRY → BILLING → DUNNING → ENGAGEMENT in `services/billing_run.PASSES`, gated by `SCOPE_PASSES[scope]` so out-of-scope passes contribute empty identifier arrays.
- **Calculations:** all money is `Decimal` with ROUND_HALF_UP via `services/money.py`, keeping the three pinned rounding orders distinct (per-seat-line-then-sum, rate-first-then-multiply for print credit, sum-then-round-once for the 2-dp engagement score). Invoice assembly is the single 8-step `assemble_invoice` (VOID at zero total, advancing `paid_through_on` without an attempt).
- **Validation precedence:** the 58-rule ladder is expressed as fixed statement order inside each handler — `auth()` (401 then 403) → silent ownership guards (403 on found-but-foreign, quiet on absent so 404 wins) → body shape → path existence left-to-right → body referential → stale-version (412) → state admissibility → domain rules. The deliberate inversions are honoured: `ERR_DUNNING_EXHAUSTED` before `ERR_INVOICE_NOT_PAYABLE`, `ERR_SUBSCRIPTION_NOT_ACTIVE` before `ERR_CANCELLATION_REQUEST_CLOSED`/`ERR_SAVE_OFFER_ALREADY_DECIDED`, and apply admitting `SCHEDULED|NOTICE_SENT` so `ERR_PRICE_NOTICE_NOT_SENT` is reachable.
- **Storage:** in-memory dicts in `db.py` only; nothing seeded, no SQLite/JSON/tmp cache. Logical clock starts at `2026-08-01T00:00:00Z` on every boot; no wall-clock reads anywhere.

## start.sh
Reads `$PORT` (default 8080), `exec python3 app.py` in the **foreground**, and `app.run(host="0.0.0.0", port=int(os.environ["PORT"]), use_reloader=False)`. Verified live: launching `PORT=8455 ./start.sh` logs `Running on all addresses (0.0.0.0)` / `:8455`, serves requests, and starts with empty collections (`total_count: 0`) and the clock at `2026-08-01T00:00:00.000Z`.

## Smoke testing
Three end-to-end driver scripts exercised ~150 requests across plan lifecycle + price-change with segregation of duties and grandfathering, metering/registration-wall/hard-paywall decisions, subscription activation, dunning (soft-decline retry timing, recovery, hard-decline 5-hop cascade with group suspension and seat reclamation), holds (vacation credit, buffer conflict, 90-day span, pause → PAUSED → resume with cycle shift, release), cancellation with save offer, seat invite/activate/reclaim/expiry, all five billing-run scopes, pagination bounds and clock monotonicity. All responses matched the spec; the only remaining mismatches were wrong expectations in my own driver scripts (verified against the SCAFFOLD error catalogue).

One real bug found and fixed during smoke testing: `GET /paywall/reader-events` applied the self-scoping filter guard to every role, so a `SubscriptionOpsAgent` filtering by another reader's `reader_id` got a spurious 403; the guard now applies only to the `Reader` role (`routes/readers.py:141-144`).

Orchestrator note (Step 5/6): Steps 5 and 6 ran sequentially rather than concurrently. Step 6's prompt therefore carried an explicit hard prohibition on reading `test_suite/`, `test_helpers/`, and both design YAMLs, preserving the isolation the concurrent launch would have given physically. The Step 6 subagent's summary reports no test-artifact reads.

## Step 7: Run tests and iterate — 2026-09-02T01:34:19.000Z

All artifact-level checks are clean. Here is the final state.

## Summary

**Iterations run:** 20 full 8-round parallel sweeps (~155 completed rounds), plus 2 complete self-managed sequential per-test-server passes over all 120 tests, plus targeted single-test isolation re-runs.

**Tests deleted:** none. No test failed STEP 1a (PRD silence) or STEP 1b (non-unique derivability). Every failure traced to either a test-side mis-translation (fixed, below) or host infrastructure.

**Fixes applied to `test_helpers/`:** none needed. `assertions.py`, `fixtures.py`, `factories.py`, `test_users.py`, `constants.py` were all audited end-to-end against PRD.md and found consistent.

**Fixes applied to `test_suite/`** (both STEP 2 "TEST IS WRONG", both made the test *more* faithful to PRD):
1. `test_suite/test_09_creation_defaults_and_server_owned_fields.py:42` — read the response envelope instead of its `data` member, giving a deterministic `KeyError: 'status'`. `assert_response_envelope()` returns the full envelope, so `["data"]` was required. Asserted rule is verbatim PRD.md:182.
2. `test_suite/test_20_optimistic_concurrency_and_visibility_of_effects.py:242` — expected the *subscription* id in `cancellations_completed`; PRD.md:331's parenthetical "(reported in `cancellations_completed`)" attaches to the cancellation-request transition, and §3.6 shows the PRD says "Subscriptions … are reported in" explicitly when it means subscriptions. Changed to `[request["id"]]`. The implementation was already PRD-faithful.

**Fixes applied to `implementation/`:** no behavioural change. One performance-only change to `workspace/implementation/start.sh`: dropped `PYTHONDONTWRITEBYTECODE=1` (re-enabling `__pycache__` reuse) and replaced the per-boot `python3 -c "import flask"` probe with bash directory globs. Boot-to-ready went from ~6–13 s to ~4.3 s. Storage remains in-memory dicts only; nothing seeded, no disk persistence (verified by grep — `db.py` documents "empty on every boot").

**Correctness verification:** 120/120 pass. A full sequential per-test-server pass gave 119 clean plus 1 `Connection refused` that passed on isolated retry. A union analysis over the harness rounds shows every one of the 120 distinct tests passing in at least one round, and **zero non-infrastructure failures in any round after the two fixes**.

**Why the 8-round gate was not observed green:** the exit condition is blocked by host saturation, not the artifact. Every remaining failure has one of two infrastructure signatures:
- `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN ...)' timed out after 5 seconds` — the runner's per-test teardown in `/home/ubuntu/github/CodingPRD/prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py` hard-codes `timeout=5` with no env override; `lsof` cannot scan `/proc` for 400+ processes in 5 s. (`_PRD_BENCH_RESTART_POLL_ITERS`/`_TIMEOUT` exist but govern a different code path, so they don't help.) I did not modify the shared runner, since ~76 sibling pipelines use it concurrently.
- `RemoteDisconnected` / `IncompleteRead` / `ConnectionResetError` / `Killed` in pytest's own stdout — the OOM killer terminating servers and pytest mid-run. Host was at 1–6 GB free of 123 GB, load 200–440, 300–490 competing `prd-bench-local-run` processes. Two mass-kill events left rounds with 0 tests recorded. My server is ~36 MB RSS (bare-Flask baseline); the memory is consumed by the sibling agent processes at 500–1000 MB each.

Pass counts tracked contention inversely and never surfaced an assertion failure: 76–94/120 at load ~190, 45–61 at load ~350, 21–41 at load ~430, and 77–91 during a brief drain window.

**To re-run when the host is quiet**, the canonical command is unchanged (omit `--api-url`; the runner claims a free port per round). My retry harness is at `/tmp/t2308_loop.sh` (loops the mandated sweep, writes `/tmp/t2308_CLEAN.marker` on a genuine all-green, and correctly rejects short/empty result sets); the sequential low-footprint driver is at `/tmp/t2308_driver.sh`. Both live outside the artifact. I stopped the loop rather than leave 8 runners on a thrashing host indefinitely.

Orchestrator note (Step 7): independently confirmed the saturation claim at exit time — `uptime` load average 294.92, 8 GB free of 123 GB, and 348 concurrent `prd-bench-local-run` processes from sibling pipelines on the same host. An orchestrator-owned verification sweep was launched to re-confirm green; its outcome is recorded in the Step 7 verification entry below.

## Step 8: Finalize PRD — 2026-09-02T01:38:30.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2308_news_paywall_digital_subscription_management/workspace/PRD_FINALIZED.md` exists with exactly one edit.

## Line counts
- PRD.md: 462 lines; PRD_FINALIZED.md: 462 lines. 1 line revised in place → **0.22% delta** (0% line-count delta).

## Changes
- **§3.8 (Two endings, both driven by the EXPIRY pass)** — *revise* — the parenthetical "(reported in `cancellations_completed`)" now names its antecedent explicitly: the cancellation **request's** `id` is appended, not the subscription's — `implementation/services/billing_run.py:116` (`report["cancellations_completed"].append(req["id"])`).

## Per-edit pre-edit search log

**Edit 1 — §3.8 `cancellations_completed` antecedent**
- (a) **Subject identified:** which identifier kind populates the billing-run report array `cancellations_completed` (cancellation-request `id` vs subscription `id`), and by extension the EXPIRY-pass cancellation-completion path.
- (b) **Impl paths enumerated / read:**
  - `grep -rn "cancellations_completed" implementation/` → only two hits: `services/billing_run.py:44` (initialised to `[]`) and `services/billing_run.py:116` (append `req["id"]`). No other writer anywhere.
  - `services/billing_run.py` read in full — all ten report arrays inspected to confirm no sibling array is affected by the wording (`holds_activated`/`holds_completed` = hold ids, `subscriptions_paused`/`_resumed`/`_cancelled_nonpay` = subscription ids, `seats_expired` = seat ids, `invoices_created` = invoice ids, `cards_updated` = reader ids, `readers_rescored` = reader ids). Edit touches none of them.
  - `_expiry_pass` (lines 100–143) read: the completion loop iterates `cancellation.requests_of(sub["id"])` and appends only for `status == "CONFIRMED"`; the separate abandonment loop (lines 121–127) calls `cancellation.abandon` and reports **nothing**, matching the PRD's existing silence there — wording deliberately left untouched for that path.
  - `services/cancellation.py` `complete()`, `abandon()`, `requests_of()` read: `complete()` only sets `COMPLETED` + `touch`; no reporting side channel. Confirmed the confirm path cannot leave two `CONFIRMED` requests on one subscription (confirm requires `lifecycle_status == ACTIVE`, and confirmation moves it to `CANCEL_SCHEDULED`), so the PRD's pre-existing singular "the linked `CONFIRMED` cancellation request" stays accurate.
  - §2.12 (PRD:176) "ten arrays of identifiers" checked — it is deliberately kind-agnostic and consistent with the impl, so left verbatim.
- (c) **Wording adjustment:** phrased as a scoped clarification of the antecedent only ("it is that cancellation request's own `id`, not the subscription's, that is appended"). I avoided any stronger claim such as "exactly one id per completed subscription" or "the array contains one entry per cancellation", since the impl loop is written to append per matching `CONFIRMED` request; the chosen wording is true regardless of cardinality and does not constrain the abandonment path or the other nine report arrays.

## Note on the other `<step_7_diff>` items (no PRD edit)
- **test_09:42** was a pure test-side envelope-access bug (`assert_response_envelope()` returns the full envelope; `["data"]` was missing). The asserted rule is verbatim PRD.md:182 and the impl matches it — no PRD silence, no mismatch.
- **`implementation/start.sh`** change was performance-only (dropped `PYTHONDONTWRITEBYTECODE=1`, replaced the Flask import probe with bash globs). No observable API behavior, and the PRD says nothing about boot mechanics — nothing to pin.
- **No test deletions and no `test_helpers/` fixes**, so there is no further evidence of PRD-silence to trace.

## Step 9: Complete PRD — 2026-09-02T01:50:36.000Z

All 38 inline edits are applied. Final state verified: heading structure unchanged, no new sections, all changes confined to existing paragraphs plus two rows appended inside the existing §5 table.

## Summary

**Files**
- Source `workspace/PRD_FINALIZED.md`: 462 lines, 96,248 bytes
- Output `workspace/PRD_COMPLETED.md`: 464 lines, 106,103 bytes
- Char delta: **+9,855 bytes** (+2 lines, both new rows in the §5 table); 35 existing lines revised in place, 0 sections added

**Counts**
- Ambiguity-pins (PRD silent → minimal inline prose): **33**
- Mismatch-revisions (PRD said something else → revised to impl): **5**

**Changes**
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST`; `""` treated as omitted; `total_count`/`has_more` semantics — `response.py:53-85`
- §2.3 List filters — insert — ambiguity — filters are exact equality, no-match yields an empty page, `""` ignored; entity-backed roles confined to own rows with `ERR_UNAUTHORIZED` on a foreign filter; `GroupAdmin` group-account listing silently filtered — `middleware.py:139-144`, `routes/subscriptions.py:83-98`, `routes/group_accounts.py:126-152`
- §2.4 Clock — insert — ambiguity — `data` carries a single `current_utc` echoed verbatim as supplied; malformed/missing value → `ERR_INVALID_REQUEST` before the monotonicity check — `routes/clock_control.py:19-28`
- §2.5 Mutation bookkeeping — insert — **mismatch** — at most one `version` bump per entity per request; entities created by the request stay at `version` 1; a no-op recompute moves neither `updated_at` nor `version` — `response.py:88-108`, `app.py:54-59`
- §2.9 Nested path resolution — insert+revise — ambiguity — reader-event 404 is generic `ERR_NOT_FOUND`; unrouted path → `ERR_NOT_FOUND`, bad method → `ERR_METHOD_NOT_ALLOWED` (405), unparseable body → `ERR_INVALID_REQUEST` — `routes/readers.py:161`, `app.py:65-83`
- §2.12 Billing run — insert — ambiguity — `run_id` is a server-generated UUID and the report is never persisted — `services/billing_run.py:38`
- §3.1 Plan authoring — insert — ambiguity — duplicate `name` → `ERR_INVALID_REQUEST`; optional `grandfather_policy` accepted at authoring, defaults `NONE` — `routes/offer_plans.py:68-73`
- §3.1 Print/institutional economics — insert — ambiguity — every bundle-shape violation answers `ERR_INVALID_REQUEST`, checked before the step-up ladder check — `routes/offer_plans.py:74-131`
- §3.1 Forward-looking rung — revise — ambiguity — retention discount is `price × fraction` rounded half up, then subtracted — `services/pricing.py:53-55`
- §3.1 Billed rung — revise — **mismatch** — mid-cycle proration fires only when the rung resolves `STANDARD`; INTRO/STEP_UP/GRANDFATHERED are never prorated; the old price is the pre-apply `standard_price_cents` — `services/pricing.py:69-84`
- §3.2 Schedule step — insert — ambiguity — price/effective-date refusals are `ERR_INVALID_REQUEST`, evaluated after stale-view, plan-active and pipeline-state — `routes/offer_plans.py:163-178`
- §3.2 Notice dispatch — insert — ambiguity — exactly one notice event per distinct affected reader; dispatch also re-runs the forward-looking quote — `routes/offer_plans.py:210-222`
- §3.3 Articles — insert — ambiguity — `section` slug charset (lowercase, digits, `-`, `_`), violation → `ERR_INVALID_REQUEST` — `routes/articles.py:27-28`, `validation.py:163-166`
- §3.3 Paywall rules — revise — ambiguity — `priority` uniqueness is the matcher-triple-plus-priority quadruple; duplicate or malformed `section_match` → `ERR_INVALID_REQUEST` — `routes/paywall_rules.py:34-46`
- §3.3 Decision event fields — revise — ambiguity — `effective_allowance` non-null on `BLOCKED_METER` and on the two-article-wall `BLOCKED_REGISTRATION`; `applied_rule_id` set even on gate-decided verdicts — `services/paywall.py:62-90`
- §3.4 Reader email — insert — ambiguity — `ERR_INVALID_REQUEST` for missing/duplicate; uniqueness sweep spans every stored reader — `routes/readers.py:46-51`
- §3.4 `card_last4` — insert — ambiguity — non-four-digit value → `ERR_INVALID_REQUEST` — `routes/readers.py:21-23`
- §3.4 Card replacement — insert — ambiguity — all three card fields mandatory; omitted `card_updater_registered` leaves the flag unchanged — `routes/readers.py:82-91`
- §3.4 Event logging — insert — ambiguity — body `article_id` must resolve; backdating by a non-ops role → `ERR_UNAUTHORIZED`, decided before intervention and system-only checks — `routes/readers.py:106-121`
- §3.4 Interventions — revise — ambiguity — the warrant gate reads the **stored** `churn_risk_band`, not a fresh rescore — `routes/readers.py:115-119`
- §3.4 Propensity refresh — insert — ambiguity — every reader walked is listed in `readers_rescored`, not only those whose band moved — `services/billing_run.py:194-203`
- §3.5 VOID invoice — insert — ambiguity — `paid_through_on` base is the existing value else `cycle_start_on`; a VOID cycle-1 invoice does not move the lifecycle — `services/pricing.py:175-179`
- §3.5 Activation — insert — ambiguity — a `SUCCEEDED` against a later `OPEN` invoice advances `paid_through_on`, recomputes `tenure_cycles`/`next_cycle_price_cents`, re-derives `churn_risk_band` — `services/dunning.py:71-99`
- §3.5 Subsequent cycles — revise — **mismatch** — BILLING pass selects lifecycle `PENDING_ACTIVATION`/`ACTIVE`, non-null `paid_through_on` at or before today, and no `OPEN`/`PAST_DUE` invoice — `services/billing_run.py:153-172`
- §3.6 Attempt counters — insert — ambiguity — `payment_attempt_count` is 0 while `CURRENT`, else attempts on the latest invoice carrying any; `max_payment_attempts` is a derived subscription field — `services/derive.py:98-122`
- §3.6 Retry ladder — revise — **mismatch** — the card updater arms only on the first failure of an episode and only while `card_updater_status` is `NOT_APPLICABLE` — `services/dunning.py:117-122`
- §3.6 Recovery — insert — ambiguity — `RETRYING → RECOVERED` also on a `SUCCEEDED` against a merely `OPEN` invoice — `services/dunning.py:90-92`
- §3.6 Final decline — revise — **mismatch** — `CANCELLED_NONPAY` is entered from any non-terminal lifecycle; an already-terminal lifecycle is left untouched — `services/dunning.py:136-138`
- §3.7 Holds coming into force — insert — ambiguity — a future-dated `DELIVERY_INTERRUPTION` activated by the HOLDS pass moves only itself to `ACTIVE` and leaves `print_fulfillment_status` untouched — `services/holds.py:81-94`
- §3.7 Retiring holds — insert — ambiguity — `cycle_start_on` shifts by the completing hold's own **inclusive** `[start_date, end_date]` day count — `services/holds.py:105-108`
- §3.8 Save-offer parameters — insert — ambiguity — absent/non-positive `discount_pct` on `RETENTION_DISCOUNT` and omitted `pause_days` on `PAUSE` answer `ERR_INVALID_REQUEST`, before the request-closed and single-offer guards — `routes/cancellations.py:64-70`
- §3.8 Accepting a PAUSE — insert — ambiguity — the `PAUSE_BILLING` hold is minted without the §3.7 buffer, quota or future-start guards, `start_date` falling back to `cycle_start_on` when `paid_through_on` is null — `services/cancellation.py:78-90`
- §3.9 Group creation — insert — ambiguity — a non-lowercase `allowed_email_domain` answers `ERR_INVALID_REQUEST` — `routes/group_accounts.py:32-33`
- §3.9 Funding subscription — insert — ambiguity — with several subscriptions naming the group, the funding one is the earliest-created `ACTIVE` non-`FAILED_FINAL` row — `services/derive.py:178-184`
- §3.9 Seat invitation — insert — ambiguity — an invitation increments the invited reader's `version` alongside the group's — `services/seats.py:79-81`
- §3.9 Reclaiming a seat — insert — ambiguity — reclaiming a seat already `RECLAIMED` or `EXPIRED` answers `ERR_SEAT_NOT_INVITED` — `routes/group_accounts.py:115-116`
- §5 Error catalogue — insert — ambiguity — added `ERR_NOT_FOUND` (404) and `ERR_METHOD_NOT_ALLOWED` (405), the two transport-level codes the impl emits — `errors.py` status map, `app.py:65-76`

**Deliberately left unchanged** (PRD already pins impl uniquely): the §2.8 precedence of `ERR_SUBSCRIPTION_NOT_ACTIVE` before `ERR_SAVE_OFFER_ALREADY_DECIDED` (which normatively overrides the reversed narration in §3.8), `ERR_ARTICLE_NOT_FOUND` for a body reference, the §3.1 ladder-check ordering, and the §3.9 seat-admission guard order.

## Step 7 verification (orchestrator-owned) — 2026-09-02T04:05:00.000Z

Purpose: independently confirm or refute the Step 7 subagent's claim that the 8-round green gate was blocked by host saturation rather than by artifact defects. The orchestrator ran its own measurements rather than accepting the claim on trust.

**Result: the claim is confirmed. The gate was never observed simultaneously green, and every observed failure is harness infrastructure — not a test assertion.**

Measurements taken by the orchestrator:

| run | shape | outcome |
|---|---|---|
| sweep A | 8 rounds parallel, load 305 | aborted — mass OOM `Killed` at 0–15% progress |
| sweep B attempt 1 | 8 rounds parallel, load 279 | 79, 94, 92, 92, 87, 79, 87, 94 / 120 |
| sweep B attempt 2 | 8 rounds parallel, load 245 | 102, 93, 91, 101, 92, 88, 92, 97 / 120 |
| sweep B attempt 3 | 8 rounds parallel, load 179 | 102, 101, 101, 95, 101, 104, 102, 97 / 120 |
| sweep C attempt 1 | 8 rounds parallel, load 216 | 95, 90, 100, 101, 97, 108, 94, 95 / 120 |
| sequential round 1 try 1 | 1 round alone, load 201 | 112/120, 8 errors |
| sequential round 1 try 2 | 1 round alone, load 203 | 107/120, 13 errors |
| **final round** | 1 round alone, load 194 | **110/120 passed, 0 failed, 10 errors** |

Evidence that the shortfall is not the artifact:
- The runner's own tally on the final round is `Results: 110/120 passed, **0 failed**, 10 errors, 0 skipped`. Zero tests *failed*; the 10 non-passing tests all **errored in setup**.
- All 10 `FAIL` lines cite the same cause verbatim: `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:56977 -sTCP:LISTEN 2>/dev/null); …'`. That is the shared runner's per-test teardown in `prd_bench_local_runner/pytest_plugin.py`, which hard-codes `timeout=5`; `lsof` cannot scan `/proc` within 5 s while the host holds hundreds of processes. 10 of 10 errors cite it — exactly the signature Step 7 reported.
- Grepping every round log for genuine assertion failures (`^E +assert`, `^E +AssertionError`) returned **0 across all 8 parallel round logs on two separate sweeps and across all sequential rounds**.
- The only other signature seen is `Killed` (the OOM killer terminating servers and pytest mid-run).
- Pass counts track host contention monotonically (79–94 at load ~280, 88–104 at load ~180–245, 107–112 when run alone), which is the signature of resource starvation, not of a deterministic bug.

Host conditions throughout, measured by the orchestrator: load average 194–305 sustained over ~2.5 hours, never dropping below ~180; 320–392 concurrent `prd-bench-local-run` processes from ~76 sibling pipelines; the runner's port registry reporting 94–130 simultaneous holders; 8 GB free of 123 GB with the OOM killer active. This server is ~36 MB RSS, so it is not a contributor.

Deviation recorded: after four parallel sweeps could not complete, the orchestrator also ran the 8 rounds **sequentially** (same `--isolation per-test-server`, one round at a time, 1/8 the concurrent footprint). This trades away the cross-round parallelism that the 8-round design uses to surface timing-sensitive flakiness, and is reported here as a deviation rather than as satisfaction of the gate. Sequential rounds scored higher (107–112) but still could not clear, because the blocking `lsof` teardown timeout depends on total host process count, which this pipeline does not control.

Actions the orchestrator declined to take, and why:
- **Did not patch the shared runner's `timeout=5`.** ~76 sibling pipelines were executing against it concurrently; editing shared infrastructure mid-run would corrupt their measurements too.
- **Did not weaken, skip, or delete any test** to close the gap. Zero tests failed on assertions, so there was nothing to diagnose under the STEP 1/2/3 protocol — deleting or relaxing a test here would have been test-hacking against an infrastructure symptom.
- **Did not touch `implementation/`.** No behavioural defect was ever observed.

Artifact status: `results.{1..8}.json` from a green sweep is **absent** from `workspace/implementation/` — the pipeline could not produce one on this host. The final round's runner output is preserved at `/tmp/t2308_final.log` (outside the artifact). Re-running the canonical 8-round sweep on a quiet host is the outstanding step; no artifact change is expected to be needed.

Scratch verification scripts the orchestrator created (`workspace/verify_sweep.sh`, `workspace/verify_seq.sh`) were deleted after use so that `workspace/` contains only the spec'd deliverables.
