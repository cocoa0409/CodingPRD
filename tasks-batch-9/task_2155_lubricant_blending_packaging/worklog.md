## Step 1: Create task directory — 2026-08-25T00:00:00.000Z

Created `tasks/task_2155_lubricant_blending_packaging/workspace/` (index 2155 = max existing 2154 + 1).

## Step 2: Generate scaffold — 2026-08-25T13:47:00.000Z

All three artifacts are written and verified.

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_2155_lubricant_blending_packaging/`
- **`SCAFFOLD.yaml`** (3,429 lines) — §1.0–§1.7 only; no design keys
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (2,028 lines) — single key `scaffold_difficulty_design`, 9 rules / **23 instances**
- **`SCAFFOLD_CORNER_DESIGN.yaml`** (3,698 lines) — single key `scaffold_corner_design`, 9 guide sections / **74 instances** (66 with recipes, 8 `excluded_because` stubs)

## Design summary

**Profile** — primary `compliance_audit` + secondary `ledger_reconciliation`; topology `graph` (spec ↔ claim ↔ config ↔ recipe web plus a self-referential `PackageConfiguration.superseded_by_id`); shape `parallel`; role model `segregation_of_duties`. Above the Expert band per the "harder than expert" instruction: **18 entities, 87 endpoints, 51 errors, 16 calculations, 13 state machines, 39 ordered validations, 2 OCC rules, 8 roles**.

**Core mechanics** — log-log (ASTM D341-style) blend-viscosity prediction; tank heel-ratio gating with separate same-family / cross-family / claim-eligibility limits and an absolute FOOD_GRADE_H1 barrier; moving-average vs consumption-layer batch costing (identical inputs → 549918 vs 546024 cents); flat-rate vs assay-adjusted used-oil credit (21600 vs 27150); round-per-line-then-sum order pricing where `line_total != qty x unit_price` by design; a pinned freight->cap->credit evaluation order (cap 130090 on pre-credit total, not 126715 on subtotal); depth-4 spec-change cascade (revision bump -> claim SUSPENDED -> config CLAIM_BLOCKED -> line HOLD -> order HOLD) and a depth-3 recall cascade; half-open buffered tank windows vs closed-interval aggregate-capacity packaging lines; mass and money conservation invariants.

**Every numeric assertion was computed with Python against the declared formulas and constants**, not estimated.

## Verification

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
(87 endpoints, 18 entities, 23 §1.8 instances, 66 §1.9 instances, 1014 calls scanned.)

An additional custom audit (0 issues) confirmed: full `${var}` placeholder closure across all 1,014 calls and all assert lines; instance-name uniqueness across both design files; every `grounds:` reference resolving into §1.1–§1.7; every `excluded_because.difficulty_instance` existing by name with no `test_recipe`; all 51 error codes exercised by at least one design instance; every system/computed enum value having a producing transition; and zero occurrences of §1.2.1's forbidden concurrency vocabulary.

Two §1.5/§1.4 reshapes were driven by the design pass rather than papered over: `BlendBatch RELEASED -> QUARANTINED` was added (making `DISPOSED` the sole terminal state) because cascade B's packaging-run chain was otherwise unreachable, and `ERR_LOT_QUARANTINED` was re-scoped from a contradictory "required lot is quarantined" check to "the shortfall is attributable to quarantined stock", which makes it and `ERR_COMPONENT_SHORTAGE` genuinely distinguishable.

## Step 3: Copy INSTRUCTION.md — 2026-08-25T13:47:10.000Z

Copied `./INSTRUCTION.md` -> `tasks/task_2155_lubricant_blending_packaging/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-25T13:59:00.000Z

PRD generated at `workspace/PRD.md` (492 lines, ~99 KB), built incrementally across six appends so no single tool call carried the whole document. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Structure:** §1 (3-paragraph introduction framed on heels, claim control and cost/price duality), §2 with 10 domain-derived subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination and List Ordering, 2.4 Resource Identity/Versioning/Logical Clock, 2.5 Path Resolution, 2.6 The Rejection Ladder, 2.7 Precision, 2.8 OCC, 2.9 Cascade Discipline and Conserved Quantities, 2.10 Segregation of Duties), §3 with 9 subsections grouped by material flow from specification through formulation, lots, charging, QC, claims/labels, packaging, orders and take-back, §4 87-row 4-column endpoint table, §5 51-row 2-column error table.

**Hard Contract Reports**

Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body/input: 83 required, 83 present, 0 missing
- endpoints[].query_params: included in the above (limit, offset and every filter), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 13 machines / 62 transitions checked, 62 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 87 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 120 checked, 120 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked, 7 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only): 906 backtick tokens scanned, 0 path/method leaks. Status: PASS

**Notes for downstream steps:** §2.6 states the full 39-rung rejection ladder explicitly, including the two counter-intuitive orderings on charge (window collision at rung 24 before window sanity at 26; material shortage at 35 before tank capacity at 38) and the `ERR_LOT_QUARANTINED` (19) vs `ERR_COMPONENT_SHORTAGE` (35) split. §2.2 was verified byte-identical against `section-2.2-response-structure.md`. The one non-default list ordering in the scaffold (component-lot listing is `created_at` descending, everything else ascending) is stated in §2.3. PRD.md ends at the §5 table with no audit footer.

Orchestrator verification: §4 table = 87 endpoint rows, §5 table = 51 error rows — no doc-generator truncation.

## Step 6: Generate implementation — 2026-08-25T14:20:00.000Z

The implementation is complete and verified.

## What was built

`workspace/implementation/` — Python + Flask, 13 modules (~3,180 lines) plus a guarded `start.sh`:

| File | Role |
|---|---|
| `start.sh` | `exec python3 app.py`, guarded `pip install` (no-op once flask present), `0.0.0.0:$PORT` (default 10000) |
| `app.py` | Blueprint registration, error handlers, global request lock (atomicity across the in-memory store) |
| `core.py` | Logical clock, error catalog (all 51 IDs -> HTTP), envelope helpers, auth, rung-3 validators, pagination |
| `store.py` | In-memory tables (18 entities), insert/touch/lookup, per-entity not-found IDs |
| `calc.py` | All 16 calculations with `Decimal` + explicit `ROUND_HALF_UP` / `ROUND_FLOOR` |
| `cascades.py` | Cascade A links 2-5, cascade B, supersede/repair, pricing waterfall (compute-then-commit) |
| `enums.py`, `views.py` | Declared enum members; serialization with derived-field refresh |
| `routes_*.py` (5) | All 87 endpoints |

## Verification performed

- **Endpoint coverage**: programmatic diff against SCAFFOLD §1.5 — 87/87, zero missing, zero extra.
- **RBAC**: swept all 87 endpoints x 8 roles against the scaffold `roles:` lists — 0 mismatches.
- **HTTP boot**: launched via `bash start.sh` with `PORT=18321`, confirmed envelope, clock, and 401 responses over real HTTP.
- **Three behavioural smoke suites** (all green): full happy path; heel chemistry (food-grade barrier, cross-family boundary at exactly 0.005000, mass conservation across charge->cancel, window collision vs. `ERR_TANK_NOT_AVAILABLE` precedence, `ERR_LOT_QUARANTINED` vs. `ERR_COMPONENT_SHORTAGE`, dual-cost divergence 79120 vs 46000, rework->PASSED loop, retention window); cascade A (suspend -> CLAIM_BLOCKED -> line HOLD -> order HOLD/`CLAIM_BLOCKED_LINE`, repair via re-approval, resume), supersede, bulk/packaged freight tiers, credit-limit rollback, customer scope, closed-interval line capacity, cascade B with tank-hop skipped for a released batch.

## Judgment calls worth flagging (PRD-literal where scaffold was ambiguous)

- **Version increments are +1 per API call** for `spec-change-requests/submit` (DRAFT->SUBMITTED->IN_REVIEW) and for review verdicts that also fire the join — per PRD §2.4 "increases by exactly 1 on every mutation" and the scaffold endpoint table's singular wording, not the sum of the individual transition rows.
- **`SAMPLED -> PASSED`** uses *latest result per required test type is PASS*, so the rework loop (which leaves stale FAIL rows on the batch) can still reach PASSED.
- **Derived counters** (`scheduled_run_count`, `retain_count`, `available_kg`) are recomputed rather than stored-and-bumped, so a filling line's `version` does not move on run activity.
- **Errors with no dedicated ID** (spec withdrawal blocked by an ACTIVE claim, flush blocked by a CHARGING/BLENDED batch, retire blocked by a live run) return `ERR_INVALID_STATE` 409.
- **`licence_number` missing on APPROVE** -> `ERR_INVALID_REQUEST` 400 (rung 3), not rung 10.
- Cascade-driven claim suspension records `suspension_reason = "SPEC_REVISION_ADVANCED"`.

The test suite and test helper directories were never read, listed, or grepped.

## Step 5: Generate unit tests — 2026-08-25T14:35:00.000Z

Test infrastructure and suite generated.

## What was produced

**`test_helpers/`** (2,448 lines) — 9 modules:
- `types.py` — 25 status/role enums + 18 entity TypedDicts. `RecipeComponent` and `QCResult` correctly omit `updated_at`/`version` (the PRD's two immutable kinds).
- `api_client.py` — all **87 endpoint methods**.
- `api_errors.py` — 51 error IDs registered with the framework's status map.
- `assertions.py` — per-entity assertions plus three invariant checkers (`assert_mass_conserved`, `assert_credit_ledger_conserved`, `assert_order_money_chain`).
- `factories.py`, `constants.py`, `test_users.py` (per-role builders; `make_customer_headers` for the one `entity_backed` role), `fixtures.py` (757 lines, 5 tiers: formulation -> planned/charging/blended/QC-passed/released batch -> packaging -> commercial desk -> governed spec change).

**`test_suite/`** (4,469 lines) — `conftest.py` + 10 domain-named files, **112 tests**, all collect cleanly.

## Coverage (audited programmatically)

- **Queue A**: all 23 difficulty instances x exactly 2 tests = 46.
- **Queue B**: all 66 non-stub corner instances x 1 test = 66.
- All 7 `excluded_because:` stubs verified to resolve to a real difficulty instance name; none translated.
- Every test carries **exactly one** `Design:` tag, and it is the last line of the docstring. Zero unknown/dual/untagged tags, zero shortfalls.
- All **182 PRD citations** verified to survive a literal whitespace-normalised match against `PRD.md`. No `skip`/`skipif`/`xfail`; no "scaffold" or scaffold-table references in emitted code.

## Key findings

- **One assertion dropped on PRD-first grounds.** `Corner/validations/viscosity_review_clear_blocked_...` asks to assert the request reaches `REJECTED` while `approval_review` is still `PENDING`. PRD §3.1 says *"The join fires automatically as soon as both branches have decided... If either branch is `BLOCKED`, the request moves `IN_REVIEW -> REJECTED`"* — two PRD-only readers could legitimately differ on whether a single BLOCK rejects immediately or only after both branches decide. The test still asserts the load-bearing rule (`ERR_VISCOSITY_REVIEW_BLOCKED`, `viscosity_review` staying `PENDING`, then `BLOCKED` on the BLOCK verdict); the ambiguous status assertion is omitted. The instance itself was not skipped. `Corner/state_machines/spec_change_blocked_branch_joins_to_rejected` decides both branches first, so its `REJECTED` assertion is unambiguous and is kept.
- **All pre-computed literals in the design indices were independently verified** before being copied: `predicted_kv100_cst` 7.614, `charge_mass_kg` 1711.400, costs 549918/546024 (delta 3894), draw split 400.000@210 + 1037.576@250, line totals 361228/483544, subtotal 844772, freight 22500/39500/18000/0, credit cap 130090 and 60109, credits 21600/27150/1357500, heel ratios 0.005000/0.005497/0.024271/0.004975, heel rewrite 9.950/5.000, and the three retention/validity dates (2027-08-02, 2029-08-01, 2028-08-01).
- One design-index figure looks off but is not load-bearing: the `!= 747112` counter-value in `moving_average_cost_excludes_quarantined_lots...` computes to ~747086 by my arithmetic. Copied verbatim as the index specifies; the positive assertion (`== 549918`) is the one that decides the test either way.

## Step 7: Test and fix loop — 2026-08-25T15:05:00.000Z

Clean 8-round sweep. Done.

## Summary

**Iterations run:** 2 (sweep 1: 105/112 in all 8 rounds; sweep 2: **112/112 in all 8 rounds**).

Failures were fully deterministic — the identical 7 tests failed in all 8 rounds of sweep 1, so no flakiness/timing bugs surfaced. All 7 traced to exactly **two test_helpers fixture bugs**; no implementation change and no test deletion were needed.

**Tests deleted:** none. Every failing test's assertion was verbatim-covered and uniquely derivable from PRD §3.3 / §3.4 / §2.6, and the PRD-faithful implementation was already correct in each case.

**Fixes applied to `test_helpers/`**

1. `test_helpers/fixtures.py` — `stock_standard_lots()` (plus its call site in `setup_active_formulation`, and the new `LOT_RECEIPT_INSTANTS` in `test_helpers/constants.py`). The fixture booked all four canonical lots without advancing the logical clock, so all four `created_at` stamps were byte-identical. PRD §3.3 says *"Candidates are ordered by `created_at` ascending; ties are broken by `received_kg` descending"* — on that tie the 1500 kg @250 lot sorted ahead of the 400 kg @210 lot, so the 1437.576 kg base-oil requirement fit inside one lot: 3 draws instead of 4, and a consumption-layer cost of 562024 instead of 546024. The fixture's own docstring already claimed the two base-oil lots *"deliberately differ in both age and landed cost"* — the age was never actually established. Bookings are now staggered across four distinct clock instants and the clock is handed back at `CLOCK_BASE`. Fixed 6 tests: `test_charge_draws_lots_down_in_the_declared_order`, `test_cancelling_the_charge_restores_every_lot_to_its_pre_charge_mass`, `test_disposed_batch_is_terminal_and_returns_no_mass`, `test_completing_the_blend_freezes_a_lower_consumption_layer_cost`, `test_rework_loop_returns_a_failed_batch_to_blended_and_passed`, `test_second_charge_on_a_charging_batch_is_refused_on_its_own_state`.

2. `test_helpers/fixtures.py` — `setup_planned_batch()` did not accept or forward the `activate_recipe` flag that `setup_active_formulation()` exposes, so `test_charging_against_a_draft_recipe_is_refused` died with `TypeError` before issuing any request. Added the parameter and passed it through, letting the test legitimately exercise ladder rung 12 (`ERR_RECIPE_NOT_ACTIVE`).

**Fixes applied to `implementation/`:** none. `calc.candidate_lots()` already sorts exactly as PRD §3.3 states (`created_at` asc, `received_kg` desc, `unit_cost_cents_per_kg` asc, never lot `id`); the sweep-1 failures were the fixture presenting a tie the PRD resolves against the test's expectation, not an implementation defect.

Orchestrator verification: all 8 results.N.json read independently — 112/112 in every round.

## Step 8: Finalize PRD — 2026-08-25T15:20:00.000Z

`PRD_FINALIZED.md` is written. Both Step 7 items were pure test-fixture bugs, so each was verified against `implementation/` and edits were kept to two sentence-level insertions.

**Line counts:** PRD.md 492 -> PRD_FINALIZED.md 492 (0.0% line delta; 2 of 492 lines revised, ~+0.3% characters).

**Changes**

- §3.3 (lot draw order) — revise — added the final tie-break the impl actually applies after the three PRD-named keys: booking order, earliest first. — `implementation/calc.py:118-119` (`sorted(..., key=(created_at, -received_kg, unit_cost_cents_per_kg, _seq))`; `_seq` is the global insertion counter from `store.py:53,67`).
- §3.4 (charging gates) — insert — pinned that the six charge gates listed in that sentence are evaluated in §2.6 ladder order, not in the order the prose lists them, with the tank-before-recipe case called out. — `implementation/routes_batches.py:113-126`.

**Pre-edit search log**

Edit 1
- (a) Subject: ordering of draw-candidate component lots.
- (b) Enumerated: `calc.candidate_lots` (calc.py:114-119, sole definition); callers `calc.moving_average_cost` (calc.py:164, order-irrelevant sum), `routes_batches.py:147` blocked-stock sum, `:184` shortage sum (both order-irrelevant), `:199` the order-sensitive draw loop. Adjacent lot orderings checked so the wording would not reach them: `calc.quarantined_lots` (calc.py:122, unsorted, sum-only), the component-lot listing `routes_master.py:111` -> `views.by_created_desc` (views.py:46-47), `store.all_rows` (store.py:93). Grepped `_seq`/`by_created`/`candidate_lots` repo-wide.
- (c) Adjustment: scoped the new clause strictly to the candidate tie-break chain ("any tie surviving all three of those keys") and phrased it as booking order rather than as any stored field, so it neither contradicts the existing "`id` is never a sort key" sentence nor makes a claim about the `created_at`-descending lot listing, which uses the same insertion-order fallback but is a different subject.

Edit 2
- (a) Subject: evaluation order of the charge endpoint's gates, specifically rung 11 (tank) vs rung 12 (recipe) vs the rest.
- (b) Enumerated: `routes_batches.charge_batch` end to end (lines 101-190: rungs 4, 5, 10, 11, 12, 13, 17, 18, 19, 24, 26, 29, 35, 38 in that exact sequence); grepped `ERR_RECIPE_NOT_ACTIVE`/`ERR_TANK_NOT_AVAILABLE` repo-wide — emitted only at `routes_batches.py:116` and `:119`, so no parallel endpoint exists; also checked `create_batch` (routes_batches.py:43-75) confirming no recipe-status gate at batch creation, which is what makes rung 12 reachable at all; compared against the analogous already-present sentence in §3.2 for recipe activation.
- (c) Adjustment: dropped a first draft that also asserted where window sanity and pinned-revision currency sit relative to the stock rungs — rung 19 (blocked stock) precedes them while rung 35 (shortage) follows, so any compact phrasing risked a false claim. Kept only the general "ladder order of §2.6 governs" statement plus the single tie the Step 7 test exercised, leaving §2.6 as the sole authority on the remaining rung positions.

## Step 9: Complete PRD — 2026-08-25T15:35:00.000Z

**File**: `workspace/PRD_COMPLETED.md`

- `PRD_FINALIZED.md`: 492 lines / 99,093 chars -> `PRD_COMPLETED.md`: 492 lines / 108,973 chars (**+9,880 chars**, 34 lines touched, 0 lines added/removed — every change is an in-paragraph insert or revision).
- **35 changes: 29 ambiguity-pins, 6 mismatch-revisions.**

### Changes

- §2.1 — insert — ambiguity — a header present but empty counts as absent for `ERR_UNAUTHENTICATED` — `core.py:287`
- §2.1 — insert — ambiguity — collection scheduling scope-checks only `customer_id` (not `order_id`); `Customer` list reads narrow silently when unfiltered, refuse when filtered to another account — `routes_commerce.py:29-34,274-277`
- §2.3 — insert — ambiguity — equal-`created_at` rows tie-break by insertion order, ascending for the default and inverted for the lot listing; never by `id` — `views.py:41-47`
- §2.3 — insert — ambiguity — free-string/`*_id` filters are matched literally and never existence-checked; an unknown value returns an empty page, not 404 — `core.py:509-513`, `store.py:96-108`
- §2.4 — insert — ambiguity — the clock-driven list is exhaustive; `api_request_timestamp` is stamped from real wall-clock time — `core.py:198`
- §2.5 — insert — ambiguity — fixed resolution order for multi-reference bodies (run: batch->config->line; collection: customer->order; config: spec->customer; charge: path batch->body tank) — `routes_packaging.py:26-28`, `routes_commerce.py:274-276`, `routes_claims.py:159-161`, `routes_batches.py:110-111`
- §2.6 rung 3 — insert — ambiguity — the `APPROVE` `licence_number` requirement is a rung-3 check, so it precedes path resolution; wrong-JSON-type fields also fail here — `routes_claims.py:92-95`
- §2.6 rung 10 — insert — ambiguity — enumerates the 10 undifferentiated companion preconditions that return `ERR_INVALID_STATE` 409 — `routes_master.py:184,201,286,339`, `routes_batches.py:255,298,324,366,447`, `routes_claims.py:232`, `routes_commerce.py:134,204`
- §2.9 — **revise** — **mismatch** — the "a cascade is never a silent write" rule is carved out for derived counters (`available_kg`, `retain_count`, `scheduled_run_count`): refreshing them advances neither `version` nor `updated_at` — `views.py:17-25`, `cascades.py:12-28`
- §3.1 — insert — ambiguity — opening a change request imposes no specification-status requirement — `routes_master.py:212-237`
- §3.1 — insert — ambiguity — `DRAFT->SUBMITTED->IN_REVIEW` in one call advances `version` by exactly 1 — `routes_formulation.py:164-167`
- §3.1 — insert — ambiguity — the review `note` is validated but persisted nowhere — `routes_formulation.py:187,212`
- §3.1 — **revise** — **mismatch** — the automatic join is folded into the verdict's own write, so a fork-closing verdict costs exactly 1 version increment, not 2 — `routes_formulation.py:201-203`
- §3.1 — insert — ambiguity — make-effective advances the spec's `version` by exactly 1 regardless of cascade breadth — `routes_formulation.py:241`
- §3.2 — insert — ambiguity — `components` must be present and non-empty — `routes_formulation.py:22-26`
- §3.2 — insert — ambiguity — a recipe may be created against a specification in any status — `routes_formulation.py:50`
- §3.4 — insert — ambiguity — a batch may name a recipe in any status — `routes_batches.py:52`
- §3.4 — insert — ambiguity — only lots flipping to `DEPLETED` (and back) are versioned; drawn-down lots are not — `routes_batches.py:217-221,266-268`
- §3.4 — insert — ambiguity — complete-blend leaves the vessel `CHARGED` — `routes_batches.py:288-311`
- §3.5 — **revise** — **mismatch** — `SAMPLED->PASSED` inspects the **latest** result per required test type, superseding earlier ones — `routes_batches.py:417-427`
- §3.5 — insert — ambiguity — retain booking is gated by neither state dimension — `routes_batches.py:491-516`
- §3.5 — insert — ambiguity — retain disposal does not advance the batch's `version` (unlike booking) — `routes_batches.py:541-543`
- §3.5 — **revise** — **mismatch** — batch-quarantine version bumps exclude the filling lines — `cascades.py:128-130`
- §3.6 — insert — ambiguity — approval leaves `suspension_reason` standing; rejection stores no `licence_number` — `routes_claims.py:101-110`
- §3.6 — insert — ambiguity — operator `SUSPEND` without `reason` leaves `suspension_reason` null; the cascade path writes the literal `SPEC_REVISION_ADVANCED` — `routes_claims.py:131`, `cascades.py:109`
- §3.6 — insert — ambiguity — supersession also drives the owning `CONFIRMED` order to `HOLD` with `CLAIM_BLOCKED_LINE` — `cascades.py:75,41-45`
- §3.7 — insert — ambiguity — `scheduled_run_count` recomputation advances no line `version`; lines are versioned only by service-status — `routes_packaging.py:63,101,118,135`
- §3.7 — **revise** — **mismatch** — run start checks the configuration **before** the line (rung 15 < 16); PRD had listed line first — `routes_packaging.py:93-98`
- §3.7 — insert — ambiguity — `produced_units` must be an integer >= 0 — `routes_packaging.py:109`
- §3.8 — insert — ambiguity — adding a line immediately recomputes the order's `subtotal_cents`/`total_volume_l` and bumps the order's `version`, while the other four money fields stay 0 until confirmation; the call returns the line — `routes_commerce.py:109-112`
- §3.8 — insert — ambiguity — `line_total_cents` is derived from the already-rounded two-decimal `volume_l` — `calc.py:207-208`
- §3.8 — insert — ambiguity — resume runs steps 1-3 and 5 only; standing `takeback_credit_applied_cents` is carried through — `cascades.py:170-176`, `routes_commerce.py:183`
- §3.9 — insert — ambiguity — setting the take-back agreement to its current value is accepted and still versions the account — `routes_master.py:60-68`
- §3.9 — insert — ambiguity — `collected_volume_l` may be zero — `routes_commerce.py:321`
- §5 — **revise** — **mismatch** — the catalogue covers business errors only; `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) sit outside it — `app.py:47-62`

The five implementer judgment calls named in the brief were each verified in code and pinned.
