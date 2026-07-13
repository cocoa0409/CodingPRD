# Worklog — task_1001_optical_retail

Scenario: 1002. Optical Retail & Online Eyewear (Warby Parker style): frame catalog & virtual try-on, prescription/PD capture & verification, home try-on kit & return, lens option/coating & pricing, insurance/FSA & out-of-network reimbursement, lab order & remake, BOPIS & exam linkage, warranty

Difficulty: Expert

## Step 1: Create task directory — 2026-07-12

Created `tasks/task_1001_optical_retail/` and `tasks/task_1001_optical_retail/workspace/` (pre-allocated path, no index scan).

## Step 3: Copy shared files — 2026-07-12

Copied `./INSTRUCTION.md` → `tasks/task_1001_optical_retail/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-07-12

Lint is clean. Scaffold generated at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_1001_optical_retail/`.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    46
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  545
```

## What was generated

**Complexity profile (Expert):** primary `workflow_orchestration` + secondary `pricing_engine`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `graph`; state-machine shape `parallel`; role model `peer_roles`; consistency `immediate`. `api_prefix: /optical`.

**13 entities:** InsurancePolicy, Store, Frame, LensOption, Customer, Prescription, HomeTryOnKit, TryOnKitItem (`common_fields: false`), ExamAppointment, Order, LabOrder, InsuranceClaim, WarrantyClaim.

**7 state machines:**
- **Order** — parallel dimensions (`fulfillment_status` × `payment_status`), advanced by different triggers.
- **LabOrder** — cyclic (`IN_PRODUCTION → REMAKE_QUEUED → IN_PRODUCTION`, remake_count capped at 2).
- **Prescription** — branching + revert loop (`SUBMITTED → REJECTED → SUBMITTED`), plus clock-driven `VERIFIED → EXPIRED`.
- HomeTryOnKit (branch/rejoin via clock-driven OVERDUE), InsuranceClaim (adjudication + VOID compensation edge), WarrantyClaim (approve/deny/supersede), ExamAppointment.

**2 concurrency rules (OCC only):** `claim-create-stale-order` (parent Order, `expected_order_version`, 412) and `warranty-create-stale-lab-order` (parent LabOrder, `expected_lab_order_version`, 412) — both true CREATE-with-supersede races.

**6 calculations:** `lens_upcharge` (tiered index selection + nested min/max high-power surcharge + prism branch + coating bundle discount), `order_price_quote` (waterfall benefit allocation; **ESTIMATED vs FINAL** variants), `oon_reimbursement` (round-per-line-then-sum, pinned — 7498 vs the wrong 7499), `customer_return_risk_score` (weighted; **ROLLING vs STRICT** variants — 70 vs 47 on identical data), `remake_liability`, `kit_late_fee`. Plus 2 named conserved-quantity invariants (frame-benefit dollars; physical try-on sample units) and 2 overlap rules with deliberately opposite interval semantics (Store: half-open + trailing buffer; Customer kit window: closed, touching endpoints collide).

**46 endpoints** (20 GET — driven by FK reverse-reachability — 26 POST, including the `/optical/_clock/set_current_utc` test-driving endpoint with the mandated `2026-05-01T00:00:00Z` default). **39 error codes.** **6 roles** (Customer = `entity_backed:Customer`; the other five `opaque`).

**§1.8:** 18 instances (2 per rule × 9 rules), all numeric asserts computed by executing the formulas.
**§1.9:** 52 instances across all 9 claim-extraction sections (49 with full recipes, 3 `excluded_because:` stubs pointing at §1.8 instances).

**One design contradiction caught and fixed mid-flight:** the original frame try-on rule combined an interval-collision capacity check with a `tryon_available = stock - PENDING` counter, which could drive availability negative for non-overlapping future kits. Resolved by making the frame gate a pure availability check (`tryon_available >= 1`) and moving the closed-interval semantics onto the Customer's single-kit-window rule, which keeps Rule 8's two interval semantics genuinely distinct and keeps the sample-unit invariant sound.

## Step 4: Generate PRD — 2026-07-12

All three hard contracts pass. The PRD is written.

**Output:** `workspace/PRD.md` — 431 lines.

## Sections written

- **§1 Introduction** — 3 paragraphs, framed from the customer-journey pain point, naming the three opinionated pillars (clinical safety, money conservation, deterministic time) and the `/optical` mount.
- **§2 Global Specifications** — 10 subsections, domain-derived titles: 2.1 RBAC (6 roles, `Customer` entity-backed vs 5 opaque operator roles), 2.2 Response Structure, 2.3 Pagination, 2.4 Identity/Timestamps/Versioning (incl. the `TryOnKitItem` exception — no `updated_at`, no `version`), 2.5 The Logical Clock (`2026-05-01T00:00:00Z` seed; sole producer of `EXPIRED` / `OVERDUE`), 2.6 Money/Counts/Rounding (floor vs round-half-up vs ceiling, by step), 2.7 OCC on parent versions (both `concurrency_rules` entries), 2.8 Cascades & Conserved Quantities (both `invariants`), 2.9 Validation Order (all 30 priority rungs with `applies_to` scopes), 2.10 Interval Semantics (the two deliberately-opposite overlap conventions).
- **§3 Business Logic** — 9 subsections grouped by lifecycle: catalog setup → prescription/verify/reject loop → exams → home try-on & risk score → order build & lens upcharge → confirm/waterfall/cancel → lab & remake cycle → insurance → warranty. All 6 calculations rendered as precise prose (no operator syntax, no fuzzy words); both `ESTIMATED`/`FINAL` and both `ROLLING`/`STRICT` variants given equal density.
- **§4** — 46-endpoint table, 4 columns. **§5** — 38-error table, 2 columns.

## Coverage audit (mechanical, run against SCAFFOLD.yaml)

```
Field coverage check:
- entities[].fields:            94 required, 94 present, 0 missing
- endpoints[].request_body:     65 required, 65 present, 0 missing
- endpoints[].query_params:     20 required, 20 present, 0 missing
- envelope/common/service-line: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority:        30 checked, 30 expressed as an ordered ladder in §2.9, 0 missing
- concurrency_rules[] OCC rejections:  2 checked, 2 expressed, 0 missing
- state_machines[].transitions:       26 checked, 26 fully expressed, 0 missing
- calculations[]:                      6 checked, 6 fully expressed, 0 missing
- validations[] conditions:           30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects/applies_to: 46 checked, 46 expressed, 0 missing
- entities[].fields[] structured:     94 checked, defaults/types/initials reconstructible, 0 missing
- sibling-branch symmetry:             6 groups — all equal density, 0 asymmetric
- invariants[] + overlap_rules[]:      2 + 2 checked, all expressed, 0 missing
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 617
- tokens starting with `/`: 0
Status: PASS
```

All 38 `errors[].id` and all 6 `roles[].name` appear verbatim; all 46 endpoint paths have a §4 row. Difficulty/corner design files were not opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-07-12

All gates green. Test infrastructure complete.

## Files written

**`test_helpers/`** (Stage 1 — 9 files)
`types.py` (entity TypedDicts + 15 status enums; `TryOnKitItem` correctly omits `updated_at`/`version` per `common_fields: false`) · `api_client.py` (all 37 endpoints under `/optical`) · `api_errors.py` (39 error IDs, registered with the framework's status map) · `assertions.py` (per-entity assertions + the two conserved-quantity checkers + an instant-parser for temporal comparisons) · `factories.py` (unique-value payload factories for `sku`/`code`/`email`) · `constants.py` · `test_users.py` (per-instance `make_customer_headers(id)` for the entity-backed Customer role) · `fixtures.py` (5 tiers: primitives → `setup_order_scenario` → `setup_confirmed_order`/`setup_delivered_lab_order` → named money scenarios → risk-score accumulation builders) · `__init__.py`.

**`test_suite/`** (Stage 2 — `conftest.py` + 12 domain-language test files, **85 tests**)

## Coverage (audited programmatically)

| Queue | Instances | Tests | Result |
|---|---|---|---|
| **A — Difficulty** (≥2 tests each) | 18/18 | 36 | no shortfall |
| **B — Corner** (≥1 test each, non-stub) | 49/50 | 49 | 1 skipped |
| **Stubs** | 3 | 0 | all 3 cross-refs resolve; none translated |

Verified: 0 untagged tests, 0 dual-tagged, 0 tags to non-existent instances, 0 non-verbatim PRD citations (150 quotes grep-checked against `PRD.md`), 0 `skip`/`xfail` markers, 0 scaffold references in emitted code.

## Instance skipped (1) — and why

**`Corner/validations/confirming_with_an_expired_prescription_rejected`** — fails the unique-derivability condition. The recipe expires a `VERIFIED` prescription via the clock, then confirms its draft order, asserting `ERR_PRESCRIPTION_EXPIRED` (422). But PRD §2.9 pins check **#10** ("Prescription verified at confirmation" → `ERR_PRESCRIPTION_NOT_VERIFIED`, 409) *above* check **#18** (`ERR_PRESCRIPTION_EXPIRED`, 422), and §2.5 makes the clock the only producer of `EXPIRED` — so a lapsed prescription is by construction no longer `VERIFIED`, and any faithful PRD-only implementer returns 409, not the 422 the yaml asserts. The design index's expected outcome contradicts the PRD's own precedence table.

Worth flagging upstream: this makes `ERR_PRESCRIPTION_EXPIRED` **unreachable at order confirmation** under the PRD as written (§2.9 #18's "confirm" arm is dead), which looks like a genuine PRD/scaffold defect rather than a test-generation gap. The verify-time arm of that error is reachable and *is* covered (`Corner/endpoints/verifying_an_already_expired_prescription_at_the_default_clock`).

## Two assertions relaxed (not dropped)

- `Customer.version == 1` on creation — PRD §2.4 says `version` "increments by exactly one on every mutation" but never pins the *initial* value; the instance's actual claim (the four seeded defaults) is fully asserted.
- `delivered_at == '2026-05-01T00:00:00.000Z'` — PRD pins the *instant* the logical clock reports, not its serialization; the test compares parsed instants via `assert_same_instant`.

Tests were not executed (no implementation exists yet); they collect cleanly and `test_helpers` imports against the real `prd_bench_local_runner.testing` framework.

## Step 6: Generate implementation — 2026-07-12

**Orchestrator note:** Steps 5 and 6 were launched sequentially rather than in a single concurrent message, so `test_suite/` already existed on disk when Step 6 began. Physical isolation was therefore replaced with an explicit hard prohibition in the Step 6 prompt (no read/list/glob/grep of `test_suite/`, `test_helpers/`, or either design YAML). The subagent confirmed on exit that it never opened them.

Implementation complete and smoke-verified end to end. Read only `SKILL.md`, `INSTRUCTION.md`, `SCAFFOLD.yaml`, and `PRD.md` — the test suite, test helpers, and the two design YAMLs were never opened, listed, or grepped.

## Files written (all under `workspace/implementation/`)

`start.sh` (guarded `pip install`, `exec python3 app.py`), `requirements.txt`, `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `schema.py`, `calc.py`, `serializers.py`, `services.py`, and `routes/{catalog,prescriptions,kits,exams,orders,lab,insurance,warranty}.py`.

## Endpoints

All 38 routes from PRD §4 under `/optical`: policies, stores, frames (+ `/{id}/try-on-kit-items`), lens-options, customers (+ list/filter), `_clock/set_current_utc`, prescriptions (capture/read/list/verify/resubmit), home-try-on-kits (request/read/list/items/ship/return), orders (create/read/list/confirm/cancel), lab-orders (read/list/start/qc/ship/deliver), insurance-claims (file/read/list/adjudicate/reimburse), warranty-claims (file/read/list/decide), exam-appointments (book/read/list/complete).

## Key modelling decisions

- **Storage**: pure in-memory dicts in `store.py`, empty on every boot. No seeding anywhere. Every list sorts by an insertion sequence (= created_at ascending).
- **Clock**: `store._clock` starts at `2026-05-01T00:00:00Z` and never reads wall time for domain comparisons. Only `POST /_clock/set_current_utc` moves it, and it is the sole producer of `EXPIRED` prescriptions (`expires_at <= now`) and `OVERDUE` kits (`due_date < now`, strict), each flip bumping the resource's `version` and re-running the risk score.
- **Parallel state machine**: `Order.fulfillment_status` and `payment_status` tracked independently. Lab-order transitions bubble up conditionally — the parent only advances when it is in the declared from-state.
- **Calculations** (`calc.py`): all money is integer cents via `Decimal`; `floor` for every percentage-on-money, `ROUND_HALF_UP` for the high-power surcharge / per-line OON reimbursement / final risk percentage, `ceil` only for late-fee days. The OON payout rounds **per line then sums**. The FINAL variant re-derives only `benefit_applied_cents` and `customer_due_cents`.
- **OCC**: the only two version-guarded writes are claim creation (`expected_order_version` → `ERR_STALE_ORDER_VERSION` 412) and warranty filing (`expected_lab_order_version` → `ERR_STALE_LAB_ORDER_VERSION` 412).
- **Validation order**: implemented literally against PRD §2.9's 30-step ladder, which takes precedence over SCAFFOLD's `preconditions` ordering where they disagree.
- **Conserved quantities**: `services.py` centralises the ledger moves so credits release exactly the reserved amount.
- **`version` bumps** only when a field's value actually changes.

One deliberate gap-fill: PRD §2.9 step 5 omits `ERR_ORDER_NOT_FOUND` from its body-reference list even though `POST /insurance-claims` takes an `order_id` in the body; used `ERR_ORDER_NOT_FOUND` (404), the only code in the catalogue that fits.

## Step 7: Run tests and iterate — 2026-07-12

The sweep is clean on the first iteration. Verification confirms it is genuine, not vacuous:

- All 8 concurrent rounds collected the full **85 tests** and reported `passed: 85, failed: 0, errors: 0, skipped: 0`.
- The 85 collected tests exactly match the 85 `def test_` functions counted across the 12 test files in `test_suite/` (4+6+6+3+4+9+13+12+7+9+7+5 = 85), so no tests were silently deselected.
- `skipped: 0` in every round confirms no `pytest.mark.skip` / `xfail` is masking anything.
- Round durations were uniform (54.08–54.18s), consistent with 8 genuine concurrent per-test-server rounds rather than short-circuited runs.

No failing test appeared in any round, so the diagnostic protocol (STEP 0 -> STEP 3) had no union set to operate on. No changes were made to `test_suite/`, `test_helpers/`, or `implementation/`.

**Iterations run:** 1 (baseline sweep passed).
**Tests deleted:** None.
**Fixes applied to `test_helpers/`:** None.
**Fixes applied to `implementation/`:** None.

**Note on flakiness:** the 8-round parallel design targets timing-sensitive bugs (concurrency-detection windows, fixture ordering, port collisions). None surfaced.

**Orchestrator independent verification:** re-read all 8 `results.{1..8}.json` directly and re-counted `def test_` across `test_suite/` — 85/85 passed, 0 skipped, collected == on-disk count. Confirmed.

## Step 8: Finalize PRD — SKIPPED — 2026-07-12

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already uniquely determined every behavior the test suite exercised, so there is no Step 7 diff to patch against. `PRD_FINALIZED.md` is intentionally absent.

## Step 9: Complete PRD — 2026-07-12

Done. `workspace/PRD_COMPLETED.md` is written.

## Counts

- **PRD.md**: 430 lines / 67,808 chars -> **PRD_COMPLETED.md**: 436 lines / 73,972 chars (**+6 lines, +6,164 chars**; 17 diff hunks)
- **Ambiguity-pins: 14** · **Mismatch-revisions: 3**

## Changes

- **§2.1 (RBAC)** — insert — ambiguity — Customer ownership also gates `GET /customers/{id}` (self only); policies, lab orders and insurance claims carry no ownership check — `routes/catalog.py:195`, `routes/lab.py:18`, `routes/insurance.py:67`
- **§2.3 (Pagination)** — insert — ambiguity — out-of-bounds / non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST` 400 (not clamped) — `envelope.py:49-61`
- **§2.3 (Pagination)** — insert — ambiguity — sort ties break on server insertion order; list filters are exact-equality — `store.py:126-128`, `routes/orders.py:130`
- **§2.4 (Identity)** — insert — ambiguity — new resources are minted at `version` 1 — `store.py:113`
- **§2.4 (Identity)** — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from real wall-clock time, not the logical clock; only `delivered_at` is logical-clock-stamped — `store.py:60,110,121`, `envelope.py:21`, `routes/lab.py:122`
- **§2.4 (Identity)** — insert — ambiguity — client-supplied instants are stored/echoed verbatim, never normalised — `schema.py:87-95`, `serializers.py:145`
- **§2.4 (Derived fields)** — **revise** — **mismatch** — a no-op re-statement is not a mutation: zero-delta ledger moves and an unchanged risk score leave `updated_at`/`version` untouched — `services.py:5-17`, `calc.py:198-205`, `routes/insurance.py:149-151`
- **§2.5 (Clock)** — insert — ambiguity — any parseable instant accepted incl. backwards moves; 200 with exactly `current_utc` + the two id lists — `routes/catalog.py:213-244`
- **§3.1 (Lens option)** — insert — **mismatch** — the `1.50/1.60/1.67/1.74` enumeration is not enforced; a `MATERIAL` with null `material_index` always yields `ERR_LENS_INCOMPATIBLE_WITH_RX` — `routes/catalog.py:144`, `routes/orders.py:58-60`
- **§3.1 (Catalog)** — insert — **mismatch** — "unique" `sku`/`code`/`email` is convention, not a server-enforced constraint; duplicates are accepted — `routes/catalog.py:82,141,170`
- **§3.4 (Kit request)** — insert — ambiguity — size gate counts *distinct* ids while `item_count`/minting count array entries — `routes/kits.py:43,69,76`
- **§3.4 (Kit return)** — insert — ambiguity — `kept_frame_ids` is mandatory; omitting it -> `ERR_INVALID_REQUEST` — `routes/kits.py:138`
- **§3.6 (Confirmation)** — insert — ambiguity — the order's `version` increments exactly once across the confirm cascade — `routes/orders.py:183,214`
- **§3.6 (Cancellation)** — **revise** — ambiguity — cancel reaches every lab order of the order (remakes included) in a cancellable status — `routes/orders.py:240-254`, `services.py:34`
- **§3.7 (Lab)** — insert — ambiguity — all three bubble-ups are guarded on the parent's current fulfillment state; a failed guard is silently skipped — `routes/lab.py:49,104-107,127`
- **§3.8 (Filing)** — insert — ambiguity — order `version` increments once per filing; a filing against a self-pay order yields `policy_id` null — `routes/insurance.py:32-60`
- **§3.8 (Adjudication / Reimbursement)** — insert — ambiguity — a policy-less claim takes the `OUT_OF_NETWORK` branch and is refused `ERR_INVALID_STATE` on reimburse — `routes/insurance.py:113-122,136-138`
- **§3.9 (Warranty filing)** — insert — ambiguity — `customer_id` is only existence- and ownership-checked — `routes/warranty.py:26-28`
- **§3.9 (Warranty decision)** — insert — ambiguity — approval writes only the warranty claim's `version`; the remake's production run leaves the already-`DELIVERED` parent order untouched — `routes/warranty.py:113-128`

No new sections were added.
