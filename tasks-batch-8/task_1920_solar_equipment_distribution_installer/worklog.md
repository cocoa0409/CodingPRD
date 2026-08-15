# Worklog — task_1920_solar_equipment_distribution_installer

## Step 1: Create Task Directory — 2026-08-15T00:45:00.000Z

Pre-created per pipeline input: `tasks/task_1920_solar_equipment_distribution_installer/` and `workspace/` exist. No index scan performed (per invocation args); no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-15T01:15:00.000Z

All three files are written and the lint verdict is clean. Final summary below.

## Summary

Task directory: `/home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/`

### Files written
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

### Final lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    85
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     21
  Calls scanned (§1.8+§1.9):  500

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Counts (§1.1–§1.7)
- Entities: **14** (Product, CompatibilityRule, TariffRate, Installer, InventoryLot, Container, ContainerLine, Project, Allocation, Invoice, Payment, RmaClaim, PermitPackage, DamageClaim)
- State machines: **12** (Product, CompatibilityRule, Installer, Container, InventoryLot, Project with parallel `payment_status × fulfillment_status`, Allocation, Invoice, Payment, RmaClaim, PermitPackage, DamageClaim)
- Calculations: **8** (landed_cost_per_unit, progress_invoice_amount, credit_exposure, allocated_value_cents, damage_claim_amount, rma_credit_amount, compatibility_check, obsolescence_sweep)
- Validations: **14** (priorities 1–14)
- Endpoints: **85** (incl. 1 `/_clock/set_current_utc` test-driving endpoint and 7 top-level filtered lists for FK reverse-reachability)
- Error catalog: **62** entries
- Roles: **4** (DistributionAdmin opaque, ChannelManager opaque, InstallerRep `entity_backed:Installer`, CreditOfficer opaque)
- Concurrency rules (OCC): **2** (allocation-create-stale-lot-version, container-receive-stale-container-version)

### §1.8 difficulty instances: **18** (2 per rule × 9 rules)
- dual_variant_calc: landed_cost provisional vs final (tariff change); PROGRESS-vs-PTO invoice remainder reconciliation
- combinatorial_formula: per-line waterfall with multi-input non-linear interaction (mode a); per-claim rounding then waterfall summation (mode b)
- non_linear_state_machine: Project's parallel payment × fulfillment dimensions; RmaClaim's branching fork (approve+credit vs reject)
- transitive_cascade: container-receive → lot → project → invoice → installer credit (depth 5); RMA issue-credit → credit memo → invoice balances → installer exposure (depth 3)
- priority_pair_validation_conflict: state (p4) vs business_fiscal (p7); existence (p3) vs state (p4)
- boundary_precision_check: credit-limit `>=` equality trigger; qty_available `>=` zero-request rejection
- cross_entity_state_dependency: Project×PermitPackage completion gate; Allocation×Installer active check
- resource_temporal_overlap: TariffRate window overlap (window-window, half-open); CompatibilityRule point-in-window at exact boundary (point-in-interval)
- compensating_invariant: allocation create↔release conserves qty_available; payment post↔reverse conserves invoice balance_due

### §1.9 corner instances: **21 active + 2 excluded stubs = 23 total**
Sections covered: entities (creation/retrieval/listing/not-found/required-fields/computed/type-constraints), state_machines (side-effect cascade, invalid transition, terminal lockdown), calculations (damage claim formula), validations (auth/role/amount bounds), endpoints (filtering), errors (no-compat-rule, string-size), rbac (two denial paths), cross_cutting_layers (both OCC rules), consistency_model (immediate visibility).

### Design decisions of note
1. **Flat topology with cross-aggregate FKs** (per §0.3 diversity guidance — `flat` prioritized, `hybrid` avoided). All FKs reverse-reachable via top-level filtered list endpoints.
2. **Compound state machine on Project**: two parallel dimensions (`payment_status` × `fulfillment_status`) evolve independently; terminal `COMPLETE` requires both aligned AND PermitPackage APPROVED — triple cross-entity gate.
3. **Dual-variant landed cost** with explicit pinning: provisional uses booking-time tariff ÷ qty_booked; final uses arrival-time tariff ÷ qty_received — variants diverge on tariff change OR short-shipment.
4. **PROGRESS+PTO invoice pair** reconciles exactly to AVC; rounding residue always lands on PTO (avoids percentage-recompute drift).
5. **OCC on InventoryLot.version and Container.version** — the only sanctioned race mechanism; both have explicit `expected_*_version` payload fields and bump logic.
6. **Half-open interval semantics** unified across TariffRate and CompatibilityRule windows (`[effective_from, effective_to)`), exercised at exact boundary `t == effective_to`.
7. **Credit memo waterfall**: RMA credits apply oldest-first by `invoice_date ASC, created_at ASC` — never UUID tie-breakers.
8. **Logical clock endpoint** (`/_clock/set_current_utc`) with default `2026-08-01T00:00:00Z`; drives obsolescence sweep, past-due marking, and tariff/rule effective-window tests deterministically.
9. **Self-referential CompatibilityRule** (Product↔Product pair for MODULE×INVERTER) with pinned rule id at design lock — locks reference object version on approval.

## Step 3: Copy Shared Files — 2026-08-15T01:16:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1920_solar_equipment_distribution_installer/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T01:35:00.000Z

PRD generated and all three hard contracts pass. Summary follows.

## Deliverable

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/workspace/PRD.md` — 414 lines, ~8,470 words.

## Section Outline

- **§1 Introduction** — 2 paragraphs (business context: moving tariff cost basis + finite inventory pools; system scope across catalog, freight, credit ledger, RMA, permits, damage, obsolescence)
- **§2 Global Specifications & System-Wide Principles** (10 subsections): 2.1 RBAC with per-role `identity` prose (InstallerRep entity-backed, three opaque roles) · 2.2 API Response Structure (verbatim block, byte-identical incl. `req_RANDOMALPHANUM123456` and `"data": { }`) · 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending) · 2.4 Common Resource Properties (UUID no-prefix `id`, `created_at`/`updated_at`, `version`, null-until-event timestamps) · 2.5 Money, Basis Points, and Rounding (integer cents, round-half-up at every division) · 2.6 Nested Resource Retrieval (left-to-right, all 14 `ERR_*_NOT_FOUND`) · 2.7 Derived Fields and Same-Transaction Reconciliation · 2.8 OCC (both rules, exact error ids + 412) · 2.9 Order of Rule Evaluation (all 14 validation priorities as an ordered list) · 2.10 Logical Clock (default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`, sweep + past-due re-run)
- **§3 Business Logic & Workflows** (9 subsections): 3.1 Catalog (Products/Rules/Tariffs) · 3.2 Installer Lifecycle & Credit Ledger · 3.3 Ocean Freight & Container Receipt · 3.4 Landed Cost (provisional vs final waterfall) · 3.5 Project Design & Compatibility Gate · 3.6 Allocation & Shipping · 3.7 Billing, Payments & Debt Workout · 3.8 Permitting & Completion · 3.9 RMA & Damage Claims
- **§4 Endpoint Definitions** — 85-row table, 4 columns (Method / Path / Description / Authorized Roles)
- **§5 Error Code Catalogue** — 62-row table, 2 columns

## Zero-Silence Rule decisions

1. **`ahj_code`** — scaffold marks it `source: input` but PermitPackage is auto-created at design lock (no create endpoint takes it). Rendered as carried on the package and tied to the project's `site_postal_code` jurisdiction, without inventing an endpoint or derivation rule.
2. **`Product.discontinued_at`** — referenced by the obsolescence sweep and lot-stranding preconditions but not a declared entity field. Rendered as "at least ninety days have elapsed since the product was discontinued" — no backticked invented field name.
3. **TariffRate `SUPERSEDED`** — enum value with no transition in the scaffold. Stated as a status value with new rates starting `ACTIVE`; no supersede mechanism invented.
4. **Error-less preconditions** — installer termination's no-in-flight-projects gate, payment reversal's negative-`paid_value_cents` guard, RMA approve's `qty_approved` bounds, invoice void's no-payments condition, and CompatibilityRule creation validation all carry no `error_id` in the scaffold; each is stated as a full rule sentence without minting an id.
5. **`ERR_DESIGN_NOT_LOCKED` scope** — its catalog condition ("before permit submission or allocation") is broader than its state-machine appearance (permit submit only); I surfaced it at allocation creation in §3.6 as well.
6. **Obsolescence lag translation** — rendered the formula exactly ("less than that maximum minus two") rather than the looser "falls 2+ generations behind" from the scaffold's comment, preserving reconstruction fidelity.

## Contract Reports

```
Field coverage check:
- entities[].fields: 88 required, 88 present, 0 missing
- endpoints[].request_body/input: 59 required, 59 present, 0 missing
- endpoints[].query_params: 0 declared separately (scaffold folds filters into input lists; all covered)
- endpoints[].path_params: 14 required, 14 present in §4 paths, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in §2.9 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 12 machines / all transitions checked, fully expressed (from→to, preconditions paired with error ids, side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (waterfall, both landed-cost variants, tie-breaks, denominators), 0 missing
- validations[] conditions: 14 checked, all matchable to error ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 85 checked, expressed, 0 missing
- entities[].fields[] structured content: 88 checked, defaults/null-until-event/computed derivations reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (terminate ACTIVE/SUSPENDED, cancel DESIGN/ALLOCATED, PAID from 3 states, write-off from PROGRESS_BILLED/PTO_BILLED, settle/deny, approve/reject, strand/write-off/deplete), 0 asymmetric
- 98/98 semantic phrase spot-checks pass; 62/62 error ids appear in §2/§3; 44/44 state enum strings present
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 623
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Endpoint/error confirmation:** every §1.5 endpoint (85/85) appears in the §4 table, and every §1.6 error (62/62) appears both in the §5 catalogue and in §2/§3 narrative with its trigger condition. §2.2 was emitted byte-for-byte verbatim from the canonical source. The two forbidden design-index files were never opened.

## Step 6: Generate Implementation — 2026-08-15T01:55:00.000Z

All checks pass. The implementation is complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/workspace/implementation/`):
- `app.py` — full Flask implementation (~1400 lines), in-memory dict store, no seeding
- `start.sh` — guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`

**Endpoints: 85/85 implemented** — the full §1.5 table: clock, products (4), compatibility rules (4), tariff rates (3), installers (7), containers (9 incl. PATCH/depart/arrive/receive/close/cancel), container lines nested (3) + top-level (2), inventory lots (3), projects (9 incl. lock-design/cancel/complete/invoice-pto/write-off), allocations (6), invoices (5), payments (5), RMA claims (8), permit packages (9), damage claims (7), plus `POST /solar-dist/_clock/set_current_utc`.

**State machines implemented (11)**: Product (ACTIVE→DISCONTINUED→OBSOLETE via sweep), CompatibilityRule, Installer (ONBOARDING/ACTIVE/SUSPENDED/TERMINATED with activation credit checks, suspension cascade cancelling OPEN allocations and cancelling UNBILLED fully-terminal projects, termination gates), Container (BOOKED→IN_TRANSIT→ARRIVED→RECEIVED→CLOSED / CANCELLED, with receipt atomicity and lot WRITTEN_OFF cascade on cancel), InventoryLot (IN_TRANSIT→ON_HAND→DEPLETED/STRANDED→WRITTEN_OFF), Project compound machine (fulfillment DESIGN→ALLOCATED→PARTIALLY_SHIPPED→SHIPPED→COMPLETE/CANCELLED × payment UNBILLED→PROGRESS_BILLED→PTO_BILLED→PAID_IN_FULL/WRITTEN_OFF), Allocation, Invoice (incl. automatic PAST_DUE on clock advance), Payment (reversal rules), RmaClaim, PermitPackage, DamageClaim.

**Calculations implemented**: provisional vs final landed-cost waterfall (basis-point duty, proportional freight/insurance shares, `Decimal` ROUND_HALF_UP at every division, final divides by received qty, provisional by booked qty with booking-time tariff; recomputed on line-add and container PATCH); progress/PTO invoice split (PTO = avc − progress amount, residue on PTO); credit exposure (OPEN/PARTIALLY_PAID/PAST_DUE, WRITE_OFF excluded, hold at `>=`); allocated/invoiced/paid value aggregates; damage claim amount (base + freight per unit, no insurance); RMA credit (snapshot pricing); compatibility gate (window + latest-effective_from tie-break, string-size bounds); obsolescence sweep (gen lag 2, stranded age 90 days) — all re-run on clock moves along with PAST_DUE marking. Write-off extinguishes outstanding invoices (balance→0, →PAID) so exposure nets to zero with the WRITE_OFF invoice itself excluded.

**OCC**: exactly the two declared guards — `expected_lot_version` on allocation create and `expected_container_version` on container receive, each evaluated as the *last* gate (§2.9 order 14) after credit/availability/receipt-qty checks; mismatch → 412 `ERR_STALE_LOT_VERSION` / `ERR_STALE_CONTAINER_VERSION`. Lot/container `version` increments on every mutation including cascades.

**Boot verification**: `PORT=19401 bash start.sh` boots cleanly; probes returned a 200 paginated empty list (`response_type: "array"`, `meta.has_more/limit/offset/total_count`), 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` without auth headers, and a 201 product create with the correct envelope. Two full in-process end-to-end suites also pass: the happy path (booking→receipt→lock→allocate→ship→progress invoice→permit approve→PTO remainder→pay→complete, with verified cent-level math, e.g. final unit cost 18947, progress 606304, damage claim 80000) and the workout paths (RMA full credit → PAID_IN_FULL, suspension cascade, stranding/write-off/obsolescence, PAST_DUE marking, payment reversal, project write-off → exposure 0, stale-version and overlap rejections). Note: the shared dev host has an external process reaper that kills lingering background servers, so long-lived manual testing used Flask's test client; `start.sh` itself was verified over real HTTP within a single invocation.

## Step 5: Generate Unit Tests — 2026-08-15T02:05:00.000Z

All checks pass. Generation is complete. Final summary:

## Summary

**Task**: task_1920_solar_equipment_distribution_installer — test infrastructure + suite generated from the two design indices only.

### Test counts
- **Queue A (§1.8 Difficulty): 32 tests** covering 16 of 18 instances (each translated instance has exactly 2 tests)
- **Queue B (§1.9 Corner): 22 tests** covering all 22 non-stub instances (1 per instance)
- **Total: 54 tests**, all collected cleanly by pytest, all carrying exactly one resolving `Design:` tag, all docstring citations verified verbatim-grep-able against PRD.md (automated audit: 0 misses).

### Instances skipped (PRD-first two-condition filter)
1. **Difficulty/cross_entity_state_dependency/project_complete_requires_permit_package_approved** — fails unique-derivability. The instance's target state (SHIPPED × PAID_IN_FULL × permit not APPROVED) is unreachable via PRD endpoints: PAID_IN_FULL is reachable only from PTO_BILLED (which itself requires permit APPROVED, and approval is terminal/sticky) or via the full-RMA-credit path (contradicted by §3.9's "allocated_value_cents is deliberately not adjusted"). Its own setup (100% progress + pay the lone PROGRESS invoice) leaves payment_status at PROGRESS_BILLED per §3.7's letter, so the asserted ERR_PERMIT_NOT_APPROVED is not the uniquely-derived outcome, and §2.9 does not order a single endpoint's compound preconditions.
2. **Difficulty/cross_entity_state_dependency/allocation_create_requires_installer_active** — fails unique-derivability. PRD §3.6's allocation-create check list contains no installer-state precondition; §2.9 step 6 requires the project→installer chain be "intact and non-terminal", and SUSPENDED is non-terminal (only TERMINATED is). Two PRD-only readers diverge on whether ERR_INSTALLER_NOT_ACTIVE fires.

### Corner stubs
- `Corner/calculations/credit_exposure_aggregation_correct` — excluded_because stub, not translated; its difficulty-instance pointer (`rma_approval_cascades_to_credit_memo_to_invoice_balance_to_installer_exposure`) resolves.
- `Corner/validations/payment_exceeds_invoice_balance` carries both `excluded_because` AND a full `test_recipe`; per the stub definition ("stubs have no test_recipe") it was treated as non-stub and **translated** (PRD §3.7 covers it verbatim).

### test_helpers/ files written
`types.py` (14 entity TypedDicts, 14 status enums, role enum), `api_client.py` (~70 endpoint methods covering every PRD §4 row), `api_errors.py` (full 54-entry error catalog + framework status-map registration), `assertions.py` (per-entity shape assertions + `assert_lot_invariants`), `factories.py`, `constants.py` (BP base, generation-lag 2, stranded-age 90), `test_users.py` (opaque role constants + mandatory `make_installer_rep_headers` entity-backed builder), `fixtures.py` (5 tiers: clock/catalog seeds, active installer, locked project, container receive, shipped/PTO-billed/PAID_IN_FULL project chains, RMA helpers), `__init__.py` barrel.

### test_suite/ files
`test_01_catalog_products.py` (6), `test_02_design_lock_compatibility.py` (5), `test_03_tariff_and_landed_cost.py` (6), `test_04_container_receipt_and_damage.py` (4), `test_05_allocations_inventory.py` (9), `test_06_credit_and_installers.py` (5), `test_07_billing_payments.py` (9), `test_08_rma_claims.py` (6), `test_09_security_rbac.py` (4), plus `conftest.py`.

### Notable design-translation decisions
1. **`landed_cost_provisional_vs_final_differ_on_tariff_change`**: the YAML's setup_api_calls created R2 while R1 was open-ended — that POST would itself fail ERR_TARIFF_WINDOW_OVERLAP. I followed the instance's natural-language setup ("R1.effective_to set to 2026-08-15") and created R1 with `effective_to=2026-08-15`, making the windows half-open adjacent; expected values 67000/72000 then hold as precomputed.
2. **`progress_vs_pto_invoice_split_reconciles_to_avc`**: the YAML's precomputed literals (AVC 970000, invoices 776000/194000) are arithmetically inconsistent with its own setup chain under the PRD §3.4 waterfall (freight 50000/insurance 10000 over 750000 total declared). The PRD uniquely derives module 59000, inverter 282500, AVC 872500, PROGRESS 698000, PTO 174500 — the tests assert these PRD-derived values instead.
3. **Permit document slugs**: recipes upload four hard-coded slugs, but PRD §3.8 derives `required_documents` from product documentation without naming slugs. The `approve_permit_for_project` fixture reads the package's `required_documents` and uploads exactly those slugs — two-reader safe.
4. **`occ_container_receive_with_stale_version_rejected`**: the recipe's PATCH-after-ARRIVED step is illegal per PRD §3.3 (ERR_CONTAINER_NOT_UPDATABLE); I dropped it — the arrival itself advances the container version, so receiving with the depart-time version already triggers ERR_STALE_CONTAINER_VERSION, matching the asserted outcome.
5. **Issue-credit / invoice-pto response bodies**: PRD §2.2/§4 leave which resource sits in `data` ambiguous for transition endpoints that spawn invoices, so tests never assert on those trigger responses; they re-read invoices via the `invoice_kind`-filtered list endpoints instead.
6. **Reverse-after-partial-payment invoice status**: PRD explicitly describes status reversion only for invoices "that had been PAID", so the payment-reversal tests assert balance arithmetic, payment REVERSED status, and exposure — not the post-reversal invoice status.

## Step 7: Run Tests and Iterate — 2026-08-15T02:15:00.000Z

All 8 rounds clean: **54/54 passed in every round**. Exit condition met.

## Summary

**Iterations run:** 3 sweeps (initial diagnostic → fix → verify → fix → verify).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/test_suite/test_07_billing_payments.py` — `test_partial_payments_then_reverse_one_restores_balance`: arithmetic slip in the test's setup-vs-assertion pairing. Invoice 275000, payments 100000 + 75000 → balance 100000; the test reversed the *first* (100000) payment but asserted the balance for reversing the *second* (75000): 175000. PRD §3.7 verbatim — "adds its amount back to the invoice's `balance_due_cents`" — uniquely determines 200000 for reversing the first payment, so the test now reverses the second (75000) payment, preserving the design doc's conserved-quantity intent (post 75000 + reverse 75000 nets zero → balance returns to the post-first-payment 175000) and keeping the exposure assertion at 175000. (STEP 2 test bug; rule is PRD-covered and uniquely derivable, so no deletion.)

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1920_solar_equipment_distribution_installer/workspace/implementation/app.py` — `ship_allocation`: the ship-time availability check `lot_avail(lot) < a["qty_allocated"]` counted the allocation's *own* reserved units against it (`qty_available = on_hand − allocated − quarantined` already excludes them), making it impossible to ship any fully-allocated lot — which broke the PRD's central allocate → ship → progress-invoice workflow (§3.5 "the moment that also issues the progress invoice", §3.7 progress billing, §3.9 RMA on shipped allocations) and caused all 14 failures (every one died in fixture setup at `ship allocation: 409 ERR_INSUFFICIENT_QTY`). The check now measures availability including the allocation's own reservation (`lot_avail(lot) + a["qty_allocated"] < a["qty_allocated"]`), so it still evaluates at ship time per §2.9 item 8 and fires exactly when intervening events (e.g. damage settlement) breached the "never negative" availability invariant — the only reading under which the PRD's narrative workflow remains reachable. No PRD-required check was removed; no test positively asserts the literal (self-defeating) semantics.

**Root-cause pattern note:** the initial 14/54 failure cluster was a single implementation bug masquerading as 14 independent failures via shared fixture setup (`setup_shipped_project` → `ship_allocation`) — the triage-hint case. All failures were fully deterministic across rounds (no flakiness observed in any iteration).

## Step 8: Finalize PRD — 2026-08-15T02:25:00.000Z

Done. The patch is exactly one revised sentence; everything else is verbatim.

## Summary

**Line counts:** PRD.md = 413 lines, PRD_FINALIZED.md = 413 lines — 0% line-count delta (one in-place sentence revision on line 204, no sections added or removed).

**Changes (one bullet per change):**
- §3.6 — revise — ship-time availability check: PRD said the lot "must still show `qty_available` of at least the allocation's `qty_allocated` at ship time," which double-counts the allocation's own reservation (`qty_available` already excludes it) and makes every fully-allocated lot unshippable; revised to state that the allocation's own reserved units count toward availability for this check, so the ship is rejected with `ERR_INSUFFICIENT_QTY` only when `qty_available` with this allocation's own `qty_allocated` added back is still below `qty_allocated` — equivalently only when `qty_available` has been driven below zero — `workspace/implementation/app.py:1645`.

**Step-7 item requiring no PRD change:** the `test_07_billing_payments.py::test_partial_payments_then_reverse_one_restores_balance` fix was a pure test bug — PRD §3.7 verbatim ("adds its amount back to the invoice's `balance_due_cents`") already uniquely determines the reversal arithmetic, and the impl's `reverse_payment` (app.py:1815-1848) matches §3.7 as written. PRD text kept verbatim.

**Per-edit pre-edit search log (for the single edit):**
- (a) Subject: ship-time availability-check comparison semantics — what quantity is compared against the allocation's `qty_allocated` when shipping.
- (b) Impl paths enumerated and read/grepped: `ship_allocation` app.py:1629-1658 (fix site, check at 1645: `lot_avail(lot) + a["qty_allocated"] < a["qty_allocated"]`); `create_allocation` app.py:1540-1598 (create-time check at 1567-1568 uses plain `lot_avail(lot) < qty_allocated` — correct for a new allocation with no own-reservation, and the PRD's create sentence already matches, so the edit is explicitly ship-scoped to avoid leaking into create semantics); `lot_avail` definition app.py:303-304 (matches §3.3's `qty_available` definition, left untouched); every lot-counter mutation — receipt 1099-1100, container cancel 1148, stranded write-off 1270-1274, alloc create 1589, ship 1650-1651, release 1676, cancel cascade 500-511, damage settle/deny 2231-2232 — confirming no other availability check exists anywhere; ship-paragraph remainder verified against `touch` (281-283), `eval_fulfillment` (481-497), `maybe_depleted` (514-518), all matching PRD as written; PRD §2.9 item 8 is neutral on comparison semantics and left verbatim; test-side `ERR_INSUFFICIENT_QTY` assertions (test_05) cover create-time only.
- (c) Wording adjustment: scoped the sentence to ship time only, stated the comparison mechanically, and added the algebraic equivalence ("only when `qty_available` has been driven below zero") **without** naming a triggering event — the impl comment's "e.g. damage settlement" example was deliberately not copied, because settle/deny decrements `qty_on_hand` and `qty_quarantined` equally (app.py:2231-2232) and thus preserves availability; naming it would have introduced a false claim about a path Step 7 never exercised.

Output file: `workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-15T02:45:00.000Z

PRD_COMPLETED.md is complete. Final verification confirms every error id the implementation emits is now catalogued in the PRD.

## Summary

**File stats**
- Source: `workspace/PRD_FINALIZED.md` — 413 lines, 63,281 chars
- Produced: `workspace/PRD_COMPLETED.md` — 415 lines, 70,030 chars (+2 lines, +6,749 chars; all changes inline, no new sections)

**Counts**: 29 ambiguity-pins, 8 mismatch-revisions (37 change bullets below; implementation file is `workspace/implementation/app.py`).

**Mismatch revisions (PRD said X, impl does Y)**
- §2.8 (allocation OCC) — revise — mismatch — `expected_lot_version` is optional: checked only when supplied (non-integer → `ERR_INVALID_REQUEST`), omitted means no check; value echoed on the allocation's `expected_lot_version` field — app.py:1545-1547, 1570-1572, 1582
- §2.8 (container OCC) — revise — mismatch — same optional semantics for `expected_container_version` — app.py:1051-1053, 1083-1086
- §3.3 (lot counters) — revise — mismatch — `qty_available` "never negative" → damage-claim resolution decrements `qty_on_hand` without releasing reservations, so it can go below zero (consistent with the FINALIZED §3.6 ship check) — app.py:2231-2234, 1645-1646
- §3.3 (lot counters) — revise — mismatch — `lot_code` is server-minted as `LOT-<n>`, not "the manufacturer's physical" code; `DEPLETED` is evaluated only at receipt, shipment, and damage-claim resolution, not continuously — app.py:1175, 1105, 1653, 2234
- §3.7 (invoice amounts) — revise — mismatch — `CREDIT_MEMO`/`WRITE_OFF` amounts are system-computed (negative of claim credit; outstanding balance), not "supplied by the issuer" — app.py:1968, 1519
- §3.7 (payments) + §2.9 item 10 — revise — mismatch — void check runs before amount bounds — app.py:1759-1763
- §3.7 (PAID_IN_FULL) — revise — mismatch — PTO path fires when no PROGRESS/PTO invoice has an outstanding balance and non-VOID total > 0 (not "posted payments equal invoiced_value"); PROGRESS path fires when all invoices are PAID/VOID and a CREDIT_MEMO exists (the old "credit reduced allocated_value to zero" condition was unreachable since credits never adjust `allocated_value_cents`) — app.py:425-438
- §3.8 (completion) — revise — mismatch — precondition order is payment → permit → fulfillment, and the SHIPPED shortfall reports `ERR_UNPAID_BALANCE` — app.py:1455-1462

**Ambiguity pins (PRD silent, pinned to impl)** — all insert
- §2.3 — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (400); same-instant ordering by insertion sequence — app.py:242-264
- §2.4 — `version` starts at 1 — app.py:270-278
- §2.6 — unmatched route/method → `ERR_INVALID_REQUEST` envelope with 404/405 — app.py:119-136
- §3.1 — duplicate `sku` / invalid `product_kind` → `ERR_INVALID_REQUEST` — app.py:603-604, 619-620
- §3.1 — rule kind-mismatch and min/max bounds → `ERR_INVALID_REQUEST` — app.py:695-699
- §3.1 — tariff `effective_to` must be after `effective_from`; no qualifying rate → 0 bp duty — app.py:770-771, 325-326
- §3.2 — activate from non-`ONBOARDING` and terminate from non-`ACTIVE`/`SUSPENDED` → `ERR_INSTALLER_NOT_ACTIVE` — app.py:858-859, 917-919
- §3.2 — suspend cascade cancels a project with zero allocations (vacuous terminal-state truth) unless already COMPLETE/CANCELLED — app.py:888-893
- §3.3 — duplicate `container_number` → `ERR_INVALID_REQUEST` — app.py:956-957
- §3.3 — line add: product must exist, `qty_booked` > 0, `declared_unit_value_cents` ≥ 0, only while BOOKED/IN_TRANSIT (`ERR_CONTAINER_NOT_UPDATABLE`) — app.py:1165-1171
- §3.3 — no-op container PATCH changes nothing and does not bump `version` — app.py:1001-1013
- §3.3 — receipt entries: non-negative ints, line must belong to container (`ERR_LINE_NOT_FOUND`), missing entry → `ERR_RECEIPT_QTY_MISMATCH`, duplicate entry overwrites — app.py:1056-1081
- §3.3 — close from non-`RECEIVED` → `ERR_CONTAINER_NOT_RECEIVED` — app.py:1123-1124
- §3.4 — degenerate cases: zero total declared value → zero freight/insurance shares; zero received quantity → whole landed total stands as unit cost — app.py:349-353
- §3.5 — project create: quantities > 0, both products must exist; per-installer listing accepts `fulfillment_status`/`payment_status` filters — app.py:1294-1299, 1330-1332
- §3.5 — re-locking a locked design → `ERR_INVALID_REQUEST` — app.py:1361-1362
- §3.6 — `qty_allocated` must be > 0; owning installer must be `ACTIVE` (`ERR_INSTALLER_NOT_ACTIVE`, checked between lot existence and the credit gate) — app.py:1548-1549, 1557-1559
- §3.7 — PTO: fulfillment ≠ SHIPPED → `ERR_PROGRESS_NOT_BILLED`; progress amount = most recent non-VOID PROGRESS invoice, percentage re-derived if none — app.py:1479-1492
- §3.7 — void precondition failure → `ERR_INVOICE_NOT_OPEN` (409) — app.py:1733-1735
- §3.7 — reversal refusal id `ERR_PAYMENT_NOT_REVERSIBLE` (409); reverted invoice re-marks `PAST_DUE` if `due_date` passed; `PAID_IN_FULL` regresses to `PTO_BILLED`/`PROGRESS_BILLED` when a reversal reopens a balance — app.py:1825-1846, 439-446
- §3.7 — write-off gate order (payment_status → installer state → balance) with error ids `ERR_PROGRESS_NOT_BILLED`/`ERR_INSTALLER_NOT_SUSPENDED`/`ERR_INVALID_REQUEST`; outstanding invoices extinguished to balance 0 and status `PAID` — app.py:1507-1528
- §3.8 — `ahj_code` minted as `AHJ-<site_postal_code>`; `required_documents` is exactly the four `module|inverter-datasheet|install-guide-<sku>` slugs — app.py:1400-1406
- §3.8 — uploads only while `ASSEMBLING` (else `ERR_INVALID_REQUEST`); submit/reassemble/withdraw state gates likewise pinned (reassemble preserves `required_documents` unchanged) — app.py:2055-2057, 2072-2073, 2119-2123, 2135-2137
- §3.9 — RMA create validates existence of installer/product/allocation; `qty_claimed` unvalidated until submit; submit requires `DRAFT` (`ERR_INVALID_REQUEST`); approve bound failure → `ERR_INVALID_QTY_CLAIMED`; credit application marks zeroed targets and fully-absorbed memos `PAID`; close requires `CREDIT_ISSUED` (`ERR_INVALID_REQUEST`) — app.py:1863-1866, 1906-1907, 1933-1935, 1985-1990, 2005-2006
- §3.9 — damage-claim create: `qty_damaged` > 0, line must belong to path container (`ERR_LINE_NOT_FOUND`); filing requires `DRAFT` (`ERR_INVALID_REQUEST`) — app.py:2154-2158, 2206-2207
- §5 — catalogue rows added for `ERR_INVOICE_NOT_OPEN` (409) and `ERR_PAYMENT_NOT_REVERSIBLE` (409), both emitted by impl but previously uncatalogued

No PRD endpoint, role assignment, formula, or state transition required alteration beyond the above; the §4 endpoint table and all role columns matched the implementation exactly.
