## Step 2: Generate Scaffold — 2026-08-14T06:20:00.000Z

All three artifacts are on disk and the scaffold lint is clean. Summary of what was generated for **task_1656_manufacturer_s_rep_agency_commission**:

### Files
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

### SCAFFOLD.yaml (§1.0–§1.7)
- **Profile**: primary archetype ledger_reconciliation, secondary temporal_windowing; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology; cyclic state machines; segregation_of_duties role model; immediate consistency.
- **13 entities**: Principal, TerritoryAgreement, RateSchedule, Rep, Customer, ProjectRegistration, Order (parallel fulfillment × commission state dimensions), OrderSplit, ReturnAuthorization, CommissionEntry (append-only ledger), CommissionStatement, SampleUnit, SampleCheckout.
- **10 state machines** with reverts/cycles/self-loops (registration resubmit + renew loop, statement dispute cycle, sample checkout loop) and a depth-4 termination sweep cascade.
- **9 calculations**: quota attainment (tier boundary inclusive, self-exclusion evaluation order pinned), per-line commission stack (base × tier multiplier + registration bonus), split waterfall (largest-remainder, HOUSE fallback), dual-variant chargeback (CURRENT_RATE provisional vs ORIGINAL_RATE final, round-per-line-then-sum pinned), dual-basis statement expectation (accrual vs cash), tolerance matching, draw-recovery waterfall, step-decay sample depreciation with residual floor, termination tail eligibility.
- **10 validations** in priority order (auth → existence → ownership → state → OCC(412) → referential → temporal → constraint → fiscal); **63 endpoints** (incl. `/_clock/set_current_utc` with mandated default 2026-08-01T00:00:00Z); **32 error codes**; **4 roles** (AgencyAdmin/Auditor opaque; Rep→Rep, PrincipalOps→Principal entity-backed); **2 OCC concurrency rules** (rate-schedule supersede on Principal.version, split override on Order.version).

### SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
- **9 rule_ids, 19 instances** (≥2 each; combinatorial_formula has 3, one per mode a/b/c). Every instance has a fully structured `setup_api_calls` chain replayed from empty DB with literal-pinned payloads, `${var}` closure, and hand-computed numeric asserts (e.g., chargeback 2,500 vs 5,000 on identical goods; accrual 50,000 vs cash 16,000 on one ledger; attainment boundary at exactly 10,000 bp → 62,500; protection end-exclusive at 2027-01-28T00:00:00Z; RMA→balance→COMMISSION_HOLD depth-3 cascade at −85,000 vs −50,000 floor).

### SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
- **9 sections** (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model), **58 instances** = 53 active with full test recipes + 5 `excluded_because` stubs pointing at covering §1.8 instances. Covers defaults/required-fields/404s, terminal lockdowns, RBAC and ownership denials, all boundary error codes (split-sum conservation, dup refs/serials/periods, RMA cumulative qty with inclusive boundary, tail-window inclusive boundary, clock regression, renew guards, RMA expiry), both OCC rules, envelope/pagination/FK-reverse lookups, and default-clock proof.

### Verification
`scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (641 calls scanned; 63 endpoints, 13 entities.) Instance names are unique across both design files; no forbidden concurrency vocabulary. One fix was needed post-draft: `{principalId}` → `{id}` in nested principal path templates to satisfy the linter's FK sub-resource check.

## Step 3: Copy Shared Files — 2026-08-14T06:21:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1656_manufacturer_s_rep_agency_commission/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T06:45:00.000Z

PRD generation is complete. The document was written to `workspace/PRD.md` (367 lines). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, read, or referenced.

**Document structure** (skeleton designed from the domain, per the diversity rules):
- §1 Introduction — 2 paragraphs (business context → system scope)
- §2 Global Specifications — 10 subsections: RBAC with per-role identity translation, verbatim §2.2 response envelope (byte-identical to `section-2.2-response-structure.md`), pagination, common resource properties (with the `CommissionEntry` `common_fields: false` exception called out), logical clock + epoch sweep, commission ledger + rep hold posture, precision/basis points, OCC, the 10-tier validation pipeline, and left-to-right nested existence checks
- §3 Business Logic — 9 subsections organized on a business-timeline strategy (line setup → reps/customers → registrations → order booking/attribution → invoicing/accrual → returns/chargebacks → statement reconciliation/settlement → samples → termination/tail/year-rollover), with all calculations rendered as precise natural language (floors, half-up rounding, largest-remainder allocation, half-open windows, pinned evaluation orders) and zero pseudocode
- §4 Endpoint table — 63 rows, 4 columns only; §5 Error catalogue — 32 rows, 2 columns only; no audit footer

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body/input: 45 required, 45 present, 0 missing
- endpoints[].query_params: 9 required, 9 present, 0 missing
- path_params: 14, array sub-fields: 18, envelope/common: 15, clock-output/OCC: 4 — all present
- TOTAL: 121 required, 121 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority tiers: 10 checked, 10 expressed as an ordered pipeline in §2.9 with per-tier error ids, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_principal_version/expected_order_version + ERR_STALE_PRINCIPAL_VERSION/ERR_STALE_ORDER_VERSION + HTTP 412), 0 missing
- state_machines[].transitions: 35 checked across 10 machines (incl. dual Order dimensions, sibling DRAFT/SUSPENDED→ACTIVE, ACCEPT/REJECT dispute siblings), 35 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (quota_attainment pinned order + inclusive boundary; order_line_commission floor+bonus; split_waterfall all four attribution branches + largest-remainder; chargeback ORIGINAL_RATE/CURRENT_RATE variants with per-line round-then-sum; statement accrual vs cash variants; 25-cent inclusive match tolerance; draw recovery 50% floor; depreciation 15%/30-day step with 20% floor; tail window inclusive), 0 missing
- validations[] conditions: all error conditions matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 63 endpoints' side effects expressed; gate scopes (ERR_LINE_TERMINATED ×4 ops, ERR_REP_ON_HOLD ×3 ops, ERR_AGREEMENT_NOT_ACTIVE ×2, ERR_NO_ACTIVE_RATE_SCHEDULE ×2) enumerated, 0 missing
- entities[].fields[] structured content: all defaults (90-day notice, 6000/10000/200 bp, 180-day tail, draw 0, renewals 0, is_override false) and null-until semantics (termination/fulfillment/RMA/reconciliation timestamps, charge/rate/commission fields) reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (attribution outcomes, chargeback variants, expectation variants, return conditions, dispute actions, activation sources, hold engage/release, statement dispositions), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 502
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. Additional spot-checks: all 32 error ids appear in §2/§3 prose and in the §5 table with correct HTTP statuses; all 51 enum/state/disposition values appear verbatim; all 63 scaffold endpoints appear in the §4 table; §2.2 verified byte-identical to the canonical source file.

## Step 5: Generate Unit Tests — 2026-08-14T07:30:00.000Z

All checks pass. The generation is complete.

**Generated** in `tasks/task_1656_manufacturer_s_rep_agency_commission/`:

**`test_helpers/` (9 files)**
- `types.py` — 16 status/role enums + 14 entity TypedDicts; `CommissionEntry` is correctly append-only (no `updated_at`/`version` per PRD §2.4)
- `constants.py` — `THRESHOLDS` (protection/renewal/checkout/RMA windows, hold floor -50,000c, 25c line tolerance, draw recovery 5000bp, depreciation constants), `CLOCK_DEFAULT`, canonical BASE rate schedule
- `api_errors.py` — all 32 PRD §5 error IDs with HTTP map registered via `set_error_http_status_map`
- `api_client.py` — 48 endpoint methods covering the full PRD §4 surface
- `factories.py`, `test_users.py` (entity-backed `make_rep_headers`/`make_principal_ops_headers` builders + opaque-role constants + `NO_AUTH_HEADERS`), `assertions.py` (per-entity assertions + `order_line`/`statement_line`/`splits_for_line`/`sum_entry_amounts` row helpers), `fixtures.py` (`setup_base_scenario` canonical BASE chain, order/registration/RMA/statement/sample lifecycle helpers, clock, filtered-list readers), `__init__.py` barrel

**`test_suite/` (12 files + conftest.py) — 91 tests**, organized by concern: envelope/pagination/auth-pipeline, master data, RBAC/ownership, agreements/schedules, booking/attribution/split-override, invoicing/rates/tiers, registrations, RMAs/chargebacks, statements/settlement, samples, termination/clock.

**Verification results**
- Coverage audit: all 19 difficulty instances have exactly 2 tests; all 53 non-stub corner instances have exactly 1; the 5 `excluded_because:` stubs are untranslated and their `difficulty_instance` cross-references all resolve. No invented baseline/smoke tests.
- Citation audit: 131 ≥8-word docstring quotes all survive literal matching against PRD.md (whitespace-normalized); every test's docstring ends with exactly one `Design:` tag copied verbatim from the source YAML; no `skip`/`skipif`/`xfail` anywhere.
- `pytest --collect-only` succeeds: 91 tests collected.

**PRD-first adjudications applied**
- `renew_window_and_limit_guards`: the second-renewal probe was moved to clock 2027-04-10 (inside the *extended* renewal window) so only `ERR_RENEWAL_LIMIT_REACHED` can fail — replaying the design's literal clock (2027-01-10) would leave `ERR_RENEWAL_WINDOW_NOT_OPEN` simultaneously applicable and PRD does not order same-priority temporal checks (validation-priority silence pattern: isolate each failing check).
- Timestamp assertions compare parsed instants, not strings — PRD pins the clock reading and day arithmetic but not the serialization format of domain timestamps.
- Dropped the designs' absolute `version == 1` assertions (PRD §2.4 says version "starts at its initial value" without pinning it to 1); all version assertions are relative ("increments by one"), which PRD pins exactly.

No instance was skipped; no gaps remain.

## Step 6: Generate Implementation — 2026-08-14T07:18:00.000Z

Implementation complete for task_1656 (Manufacturer's Rep Agency & Commission Splits). All files live in `workspace/implementation/`.

**Layout** (Python + Flask, per skill mandate):
- `start.sh` — executable, guarded install (`python3 -c "import flask"` check, so per-test reboots skip pip), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — entry point, blueprint registration, envelope-consistent error handlers
- `db.py` — empty-at-boot in-memory stores (zero seeding), logical clock (default `2026-08-01T00:00:00Z`), ISO-8601 3-fractional-digit timestamping, `touch()`/`stamp_new()` common-field management (id/created_at/updated_at/version)
- `errors.py` — full 32-error catalog with exact IDs and HTTP statuses from the scaffold
- `response.py` — `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, min 1, cap 100), `created_at`-ascending list sort with insertion-order tie-break
- `middleware.py` — `X-User-ID`/`X-User-Role` auth with entity-backed resolution for Rep/PrincipalOps, per-route role gating
- `services.py` — attribution waterfall (REGISTERED > SPECIFY > SHIP_TO > HOUSE), pinned quota-attainment rating (pool-before-order, floor bp, inclusive tier boundary), largest-remainder allocation (share_bp DESC, tie-break Rep.created_at ASC), dual-variant chargebacks (CURRENT_RATE provisional / ORIGINAL_RATE final, per-line round-half-up then sum), statement expectation (accrual + cash variants, 25-cent inclusive line tolerance), draw-recovery waterfall (50% floor skim), step depreciation (15%/30d, 20% floor, damaged=50%), re-attribution cascades, and the full epoch sweep
- `routes/` — clock, principals (+agreements +rate-schedules), reps (+adjustments, +customers), registrations, orders (+PUT splits +order-split reads), rmas (+commission-entry reads), statements, samples — all 56 endpoints from the PRD table

**Key spec decisions traced to PRD prose:** validation pipeline order per §2.9 (state → OCC → linked gates → temporal → shape → fiscal); OCC via `expected_principal_version`/`expected_order_version` returning 412; version bumps on every mutation including cascades (RMA receipt and invoice mutate the principal's YTD pool and bump its version); hold asymmetry (engage < -50000, release only at >= 0); invoice rates the order against the pool *before* the order joins it; protection matched on `placed_at` within the half-open window; override split rows never re-attributed; settle reachable from IN_RECONCILIATION or DISPUTED so `ERR_UNRESOLVED_DISPUTES` fires per the catalog; window check precedes renewal-limit check.

**Verification:** two smoke suites (85 assertions total) run against the live server all pass — covering attribution splits, OCC 412s, tier boundaries, largest-remainder cents, RMA chargebacks, statement reconcile/dispute/settle with draw recovery, sample buffer/depreciation/hold engage-release, renewal window/cap, year rollover, termination cascade, and inclusive tail invoicing. The `bash start.sh` evaluator contract was verified end-to-end: two consecutive fresh boots both show an empty store and a clock reset to the default (setting the clock to exactly `2026-08-01T00:00:00Z` correctly returns `ERR_CLOCK_REGRESSION`), confirming no cross-boot state carryover for per-test-server isolation.

## Step 7: Run Tests and Iterate — 2026-08-14T07:50:00.000Z

Clean 8-round parallel sweep achieved: **all 8 rounds report 91/91 passed, 0 failed, 0 errors** (`results.1.json` … `results.8.json` in `workspace/implementation/`).

**Iterations run:** 2 (first sweep: 9 distinct failures, deterministic across all 8 rounds; second sweep: fully clean).

**Tests deleted:** none — every failing test traced to verbatim PRD prose.

**Fixes applied to `test_suite/` (test bugs, per STEP 2):**
- `test_suite/test_07_registrations.py` — added missing `create_rep` import; `test_rep_on_hold_blocks_registration_submit` died with `NameError` before exercising the PRD §2.6 hold gate.
- `test_suite/test_11_termination_cascades.py` — added missing `ship_order` and `invoice_order` imports; `test_tail_period_invoice_window_boundary` died with `NameError` before exercising the PRD §3.5 tail window.
- `test_suite/test_09_statements.py::test_settle_posts_adjustments_payments_and_zeroes_balances` — the assertion built a last-wins dict `{rep_id: amount}` over ADJUSTMENT entries, assuming one entry per rep. PRD §3.7 says the delta "produces ADJUSTMENT ledger entries … allocated across the matched order's split rows" (per-split-row entries; the 2-line order yields 4). Fixed the test to accumulate per-rep sums (the uniquely derivable invariant: {r1: 15, r2: 10}).
- `test_suite/test_09_statements.py::test_settle_on_disputed_statement_fails_state_check_first` — assertion mis-translated the PRD: it expected `ERR_INVALID_STATE_TRANSITION` from a scaffold priority-pair design, but PRD §3.7 verbatim names the outcome for this exact scenario ("any line still `DISPUTED` blocks it with `ERR_UNRESOLVED_DISPUTES`"), and a state-gate-first reading would render that sentence unreachable (a DISPUTED statement always carries a DISPUTED line). Re-pinned the assertion to `ERR_UNRESOLVED_DISPUTES`.

**Fixes applied to `implementation/` (implementation bugs, per STEP 3):**
- `workspace/implementation/db.py::new_id` — returned `uuid.uuid4().hex` (dashless); PRD §2.4 requires "a server-minted UUID", whose canonical text form is dashed. Changed to `str(uuid.uuid4())`. Fixed 4 tests (`test_success_envelope_shape`, `test_principal_creation_applies_defaults`, `test_customer_creation_persists_territory_pair`, `test_rep_territory_overlap_rejected`).
- `workspace/implementation/services.py::reattribute_for_registration` (+ new `latest_agreement` helper) — re-attribution used `active_agreement()` only, so after the §3.9 termination cascade (which terminates the agreement *before* expiring registrations) protected lines lost all split rows instead of re-resolving precedence. Now falls back to the principal's most recent agreement when none is ACTIVE, so SPECIFY/SHIP_TO rows summing to 10,000 bp are rebuilt per §3.3/§3.4. Fixed `test_termination_sweep_expires_registration_and_reattributes`.

No flakiness observed: the failure union was identical across all 8 rounds in both sweeps.

## Step 8: Finalize PRD — 2026-08-14T08:05:00.000Z

`PRD_FINALIZED.md` is written at `workspace/PRD_FINALIZED.md`. Exactly two inline revisions; everything else verbatim.

**Line counts / delta:** PRD.md = 367 lines, PRD_FINALIZED.md = 367 lines (0% line-count delta; 2 of 367 lines modified, ~0.5%).

**Changes (one bullet each):**
- §2.4 — revise — the `id` bullet now pins the canonical hyphenated text form (lowercase 8-4-4-4-12), which "a server-minted UUID" alone left open (dashless `uuid4().hex` vs dashed `str(uuid4())`) — `implementation/db.py:48-49` (`new_id`).
- §3.3 — revise — the re-attribution paragraph now pins which agreement's share terms the re-resolved §3.4 waterfall reads: the principal's `ACTIVE` agreement if one exists, otherwise the most recently created agreement in any status (the §3.9 cascades terminate/expire the agreement before expiring its registrations, so without this pin protected lines lost their split rows instead of rebuilding SPECIFY/SHIP_TO rows) — `implementation/services.py:46-57` (`latest_agreement`), used at `implementation/services.py:273`.

**Step 7 items with no PRD edit (deliberately):**
- `test_07_registrations.py` / `test_11_termination_cascades.py` import fixes — pure fixture bugs; §2.6 hold gate and §3.5 tail window are already PRD-pinned and impl-matching (`routes/registrations.py:38-39`, `routes/orders.py:207-218`).
- `test_settle_posts_adjustments_payments_and_zeroes_balances` — test bug; §3.7's "ADJUSTMENT ledger entries … allocated across the matched order's split rows" already determines per-split-row entries (contrast with §3.5's explicit per-(rep, order) ACCRUAL phrasing). Impl confirms: `routes/statements.py:289-302` posts one entry per non-house split row with nonzero cents — zero-amount and house-row skips are separately pinned by §2.6 ("never zero") and §3.4 ("no ledger entry … for a null-`rep_id` row"). Verbatim kept.
- `test_settle_on_disputed_statement_fails_state_check_first` — test bug; §3.7 verbatim pins `ERR_UNRESOLVED_DISPUTES` for this scenario; impl matches at `routes/statements.py:261-262`. Verbatim kept.

**Per-edit pre-edit search log:**

*Edit 1 (§2.4 UUID form):*
- (a) Subject: wire text form of the server-minted resource `id`.
- (b) Enumerated: `db.new_id()` (db.py:48-49) is the sole id mint — `str(uuid.uuid4())` (dashed lowercase); reached via `db.stamp_new` (db.py:107-114) at all 12 creation sites (`routes/principals.py:41,151,262`; `routes/reps.py:41,106`; `routes/registrations.py:58`; `routes/samples.py:56,123`; `routes/rmas.py:87`; `routes/statements.py:103`; `routes/orders.py:148`; `services.py:155` split rows) and directly for ledger entries (`services.py:98`). `new_request_id` (db.py:52-53) is a different field (`api_request_id`, separately pinned by §2.2). No code parses/reformats ids; path params are exact dict-key lookups.
- (c) Adjustment: wording scoped strictly to the resource-`id` bullet; no claim about `api_request_id`. Example UUID added to make the 8-4-4-4-12 grouping unambiguous.

*Edit 2 (§3.3 re-attribution agreement):*
- (a) Subject: which agreement supplies share terms when the §3.4 precedence waterfall is re-resolved during re-attribution.
- (b) Enumerated: `reattribute_for_registration` (services.py:261-285, agreement resolved at :273); `latest_agreement` (services.py:46-57: ACTIVE first, else latest-created in any status, else None); all four callers — termination cascade (services.py:330-338, agreements TERMINATED first → fallback), agreement-expiry cascade (services.py:341-349, agreement EXPIRED first → fallback), natural expiry sweep (services.py:351-355, usually ACTIVE present), withdrawal (`routes/registrations.py:190-191`, ACTIVE present). Off-site paths checked for wording conflicts: invoice tail gate (`routes/orders.py:208-218`) uses a *different* rule (most recently updated TERMINATED agreement, 180-day default) — my sentence is scoped with "re-resolved here" so it makes no claim there; booking attribution (`routes/orders.py:83-86`) still hard-requires ACTIVE with `ERR_AGREEMENT_NOT_ACTIVE` — untouched. The None branch (principal with zero agreements) is unreachable for protected lines (approval requires an ACTIVE agreement, registrations.py:110-112; agreements never deleted) and was deliberately left unpinned.
- (c) Adjustment: added "whatever its status" so the wording also covers a newer DRAFT/SUSPENDED agreement being latest-created, matching `latest_agreement`'s status-agnostic `_seq`-max selection; named both §3.9 cascade kinds (terminated *or* expired) to cover sweep steps 1 and 2.

## Step 9: Complete PRD — 2026-08-14T08:30:00.000Z

Task complete. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

**Summary**

- Source: `PRD_FINALIZED.md` (existed) → copied to `PRD_COMPLETED.md`. Lines: 367 → 367 (all edits are in-paragraph; no new sections/paragraphs). Bytes: 59,617 → 64,486 (char-delta +4,869).
- Counts: **27 ambiguity-pins, 1 mismatch-revision** (26 paragraphs touched; a few bullets bundle co-located pins).

Changes (section — insert|revise — class — what — impl ref):

- §2.3 — insert — ambiguity — limit >100 clamps to 100; non-integer limit/offset, limit<1, offset<0 → ERR_INVALID_REQUEST — response.py:20-44
- §2.3 — insert — ambiguity — created_at ties order by creation sequence — response.py:47-49
- §2.5 — insert — ambiguity — missing/unparseable `to_iso8601` → ERR_INVALID_REQUEST — routes/clock.py:17-19
- §2.5 — insert — ambiguity — `swept_counts` carries exactly 8 named keys — services.py:313-322
- §2.9 — insert — ambiguity — unparseable body treated as empty object; absent/wrong-typed body-reference ids fail ERR_INVALID_REQUEST before existence, except registration submission (`principal_id`/`customer_id`) and adjustment `principal_id`, which report ERR_NOT_FOUND; orders/RMA/statement/split-override payload shape precedes body-reference resolution — middleware.py:52-55, registrations.py:26-29, reps.py:78-81, orders.py:46-79,301-312, rmas.py:36-48, statements.py:46-62
- §2.9 item 4 — insert — ambiguity — ownership enforced only on mutations; reads ownership-free for all roles — all GET handlers (ALL_ROLES, no ownership check)
- §3.1 — insert — ambiguity — principal create validation (name/quota/notice_period_days) — principals.py:22-30
- §3.1 — insert — ambiguity — agreement create validation (codes array, timestamps, bool, share ranges [0,10000], non-negative tail) — principals.py:117-139
- §3.1 — insert — ambiguity — rate-schedule create validation (non-empty typed arrays, non-negative bonus, required integer `expected_principal_version`) — principals.py:221-246
- §3.2 — insert — ambiguity — rep create validation — reps.py:20-28
- §3.2 — insert — ambiguity — customer create validation — reps.py:96-104
- §3.3 — insert — ambiguity — `family_code`/`project_name` required non-empty — registrations.py:40-45
- §3.4 — insert — ambiguity — absent/empty `lines` array → ERR_INVALID_REQUEST — orders.py:56-58
- §3.4 — revise — ambiguity — split override: non-empty array; foreign line_id/negative share → ERR_SPLIT_SUM_INVALID; missing/non-int share_bp → ERR_INVALID_REQUEST; response is the replacement rows array — orders.py:301-355
- §3.5 — revise — ambiguity — tail window reads `tail_period_days` from earliest-created TERMINATED agreement, default 180 when none — orders.py:208-218
- §3.5 — insert — ambiguity — invoice re-validates each line's family against the active schedule → ERR_UNKNOWN_FAMILY_CODE — orders.py:203-206
- §3.5 — insert — ambiguity — no attainment tier reached → multiplier 10,000 bp — services.py:229-248
- §3.5 — insert — ambiguity — allocation ties: house rows rank after rep rows, same-instant reps by creation sequence; zero-sum (rep, order) ACCRUAL posts no entry — services.py:197-223, orders.py:250-256
- §3.6 — insert — ambiguity — RMA lines: non-empty, order-owned line_ids, no duplicates, positive qty — rmas.py:39-63
- §3.6 — insert — ambiguity — provisional estimate floors the rate to whole bp; no ACTIVE schedule/absent family → zero rate — rmas.py:109-125
- §3.6 — insert — ambiguity — final chargeback: never-invoiced line (null applied rate) prices at zero — rmas.py:118-119
- §3.6 — insert — ambiguity — zero-sum CHARGEBACK posts no entry — rmas.py:189-195
- §3.7 — insert — ambiguity — `period_label` strict YYYY-MM (month 01-12); non-empty lines; integer `amount_cents` — statements.py:48-71
- §3.7 — revise — **mismatch** — line expectation boundary: "on or before the end of the period month" → "strictly before the first instant of the following month" — statements.py:160-162
- §3.7 — revise — ambiguity — accept/dispute legal from IN_RECONCILIATION or DISPUTED; dispute needs non-empty reason and a line not already DISPUTED/RESOLVED; respond requires statement and line DISPUTED; unknown action → ERR_INVALID_REQUEST — statements.py:182-251
- §3.7 — revise — ambiguity — settle state gate (IN_RECONCILIATION/DISPUTED else ERR_INVALID_STATE_TRANSITION); delta allocated in a single largest-remainder pass with weight base 10,000 × covered lines; zero-share rows post no entry — statements.py:257-302
- §3.8 — insert — ambiguity — sample-unit field validation (non-empty serial/family, positive integer value_cents) — samples.py:36-44
- §3.8 — insert — ambiguity — "started thirty-day month" = whole days ÷ 30 floored (first step at day 30) — services.py:301-305

Everything else in the implementation (endpoint table, state machines, gates and their pipeline ordering, OCC guards, attribution waterfall, rating order, chargeback rounding order, settlement waterfall, sweep categories/order, hold asymmetry, ledger field nullability) was already uniquely pinned by PRD_FINALIZED.md and verified against the code with no change needed.
