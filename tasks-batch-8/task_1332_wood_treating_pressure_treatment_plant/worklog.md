# Worklog — task_1332_wood_treating_pressure_treatment_plant

## Step 1: Create task directory — 2026-08-12T22:10:00.000Z

Task directory `tasks/task_1332_wood_treating_pressure_treatment_plant/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; treated as DONE per instructions.

## Step 2: Generate scaffold artifacts — 2026-08-12T22:46:30.000Z

## Summary

Generated a complete PRD benchmark scaffold for the **Wood Treating & Pressure-Treatment Plant** scenario, with maximum depth/breadth as requested.

### Output file paths
- `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/SCAFFOLD_CORNER_DESIGN.yaml`

### SCAFFOLD.yaml (§1.0–§1.7)
- **Entities**: 12 — TreatmentPlant, TreatmentCylinder, PreservativeConcentrate, CustomerAccount, Charge (OCC parent), ChargePiece, TreatmentCycle, RetentionAssay (immutable), QualityInspection, DripPadLog (immutable), WarrantyRegistration, CylinderScheduleSlot (immutable)
- **State machines**: 9 with 45 total transitions (branching + cyclic on Charge and Cylinder; terminal lockdowns on Plant/Customer; piece bubble-up cascades)
- **Concurrency rules**: 2 OCC rules on Charge (`charge-retreat-stale-version`, `warranty-register-stale-charge`)
- **Calculations**: 7 — provisional_retention_calc (forward_looking), final_retention_calc (chronological, nested rounding), registration_fee_calc (tiered, 4-input), hazard_liability_calc (threshold), cylinder_capacity_check (aggregation), slot_overlap_check (interval_merge, half-open + buffer), assay_outcome_rule (threshold)
- **Validations**: 19, ordered priority 1–19 across auth/existence/state/business_safety/business_temporal/business_referential/business_fiscal/business_constraint
- **Endpoints**: 99 (includes 2 test-driving `/_clock/set_current_utc`, `/_charges/{id}/force-state`, plus flat collection + filtered-list GETs to satisfy FK reverse-reachability)
- **Errors**: 44 domain-specific codes
- **Roles**: 6 (PlantOperator, LabTechnician, QualityManager, QualityAgencyInspector, ComplianceOfficer, AccountsReceivable) with **segregation_of_duties** role model
- **Complexity profile**: posture_driven_gating + compliance_audit; layers = optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers

### SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
- **9 rule blocks**, **19 instances total** (≥2 per rule, 3 for combinatorial_formula)
- All rules satisfy differentiation clauses (different entity domains, different error-category pairs, different metrics, different interval semantics, different conserved quantities, etc.)

### SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
- **9 section blocks**, **33 instances total** spanning: entities (9), state_machines (6), calculations (3), validations (5), endpoints (2), errors (1), rbac (3), cross_cutting_complexity_layers (3), consistency_model (1)

### Verification
- All three files parse as valid YAML
- `scaffold_lint.py` verdict: **clean lint** — 99 endpoints, 12 entities, 19 §1.8 instances, 33 §1.9 instances, 478 calls scanned, zero violations

(Note: the subagent's first pass stopped after planning without writing files; orchestrator resumed it via SendMessage and it completed all three files. Orchestrator independently verified all three files exist and parse as valid YAML with the required top-level keys.)

## Step 3: Copy shared files — 2026-08-12T22:47:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1332_wood_treating_pressure_treatment_plant/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: Generate PRD — 2026-08-12T23:09:00.000Z

All contracts pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/workspace/PRD.md` — 366 lines.

**Section list:**
- §1. Introduction (2 paragraphs, business-context angle; API mounts named here)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (6 roles, all `identity: opaque` translated individually)
  - 2.2 API Response Structure (emitted verbatim — diff against `section-2.2-response-structure.md` is byte-identical)
  - 2.3 Pagination, Sorting, and List Filtering (limit 10/1/100, offset 0, `created_at` ascending, all query filters enumerated)
  - 2.4 Resource Identity and Common Properties (incl. explicit `updated_at`/`version` absence for RetentionAssay, DripPadLog, CylinderScheduleSlot)
  - 2.5 Licensing Posture and the Plant Compliance Score (score 1000 start, 0 floor, 300 suspend exposure, four gated operations)
  - 2.6 Numerical Precision and Rounding
  - 2.7 Optimistic Concurrency Control on Charge-Mutating Writes (both OCC rules with endpoint, `expected_charge_version`, `ERR_STALE_VERSION`/412, stale-version framing only)
  - 2.8 Nested Path Resolution and Existence Checking (left-to-right, all 12 NOT_FOUND ids)
  - 2.9 Validation Evaluation Order (explicit 19-step priority cascade)
  - 2.10 Logical Time and Test-Driving Hooks (clock default 2026-08-01T00:00:00Z, force-state)
- §3. Business Logic & Workflows — 9 subsections (Plant Governance / Cylinder Fleet & Slots / Preservatives / Customer Credit / Charge Loading / Cycle Execution / Assay & Re-Treat Loop / Incising-DripPad-Tagging-Release / Agency Inspections), scattered, path-free
- §4. Endpoint Definitions — 96-row table, 4 columns only; verified to match the scaffold's 96 unique method+path pairs exactly (empty diff both directions)
- §5. Error Code Catalogue — 44-row table, 2 columns only

**Zero-Silence Rule audit (Hard Contracts):**

```
Field coverage check (Contract 1):
- entities[].fields + common fields: 78 required, 78 present, 0 missing
- endpoints[].request_body-only ids (new_assay_pct, additional_gallons, reason,
  amount_cents, piece_manifest, expected_charge_version, abort_reason,
  to_iso8601, target_status): 9 required, 9 present, 0 missing
- query_params (limit, offset, status, severity, use_category, customer_id,
  cylinder_id, charge_id, preservative_id, cycle_id, slot_kind, from_iso,
  to_iso, containment_breach, plant_id): 15 required, 15 present, 0 missing
- path_params (plantId … slotId): 12 required, 12 present (§2.8 prose + §4 paths), 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority: 19 checked, 19 expressed in ordered §2.9 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint +
  expected_charge_version + ERR_STALE_VERSION/412 named; no race framing), 0 missing
- state_machines[].transitions: 42 checked across 10 machines, 42 fully expressed
  (from/to, preconditions+error_id, side effects incl. cascades), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise reconstruction-grade prose
  (provisional/final retention, fee tiers with pinned rounding order, hazard
  liability, capacity boundary, half-open slot overlap, assay outcome rule), 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (e.g., ERR_PLANT_NOT_LICENSED
  four-operation scope, ERR_CUSTOMER_CREDIT_HOLD two-endpoint scope), 0 missing
- entities[].fields[] structured content: defaults, enum sets, initial/terminal
  states, common_fields:false exceptions all reconstructible, 0 missing
- sibling-branch symmetry: close pass/fail, piece follower pairs, drain/complete/abort,
  preservative auto-transitions — equal density, 0 asymmetric
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 425
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Supplementary checks:** all 44 error IDs appear in §2/§3 prose (not just §5); all 78 enum/state values present; no fuzzy/approximating words in rule contexts; no operator pseudocode outside the verbatim JSON fences. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) and all sibling task directories were not accessed.

## Step 5: Generate unit tests — 2026-08-12T23:45:00.000Z

All 70 tests collect cleanly. Generation complete — final summary:

## Summary

**Task**: task_1332_wood_treating_pressure_treatment_plant — test infrastructure + suite generated.

### Counts
- **Queue A (Difficulty)**: 39 tests covering all **19/19 instances**, each with ≥2 tests (one instance has 3).
- **Queue B (Corner)**: 31 tests covering **31/33 non-stub instances** (no `excluded_because:` stubs exist in the index).
- **Total**: 70 tests, all collected cleanly by pytest; zero `skip`/`skipif`/`xfail` marks.

### Instances skipped (PRD-first filter failures)
1. **`Corner/calculations/assay_outcome_marginal_vs_gross_boundary`** — the recipe asserts FAIL_MARGINAL for mean == target with min < pass_threshold, but the PRD §3.7 outcome rule defines no branch for that input combination (PASS needs min ≥ threshold; FAIL_MARGINAL needs mean < target; FAIL_GROSS needs mean < threshold). Outcome is underdetermined → fails unique derivability.
2. **`Corner/cross_cutting_complexity_layers/rate_threshold_preservative_low_stock`** — the low-stock gallon threshold value appears nowhere in the PRD, so "500 gal → LOW_STOCK, replenish +100 → IN_STOCK" is not uniquely derivable (the threshold is unobservable and there is no API path to force LOW_STOCK deterministically).

### Key derivability adaptations (tests emitted, assertions adjusted to PRD-derivable form)
- The use_category → `target_retention_pcf` **lookup values are never stated in the PRD**, so no test asserts literal targets (0.25/0.40/0.60). All assay-driving tests read the server-computed target and derive pass/marginal/gross inputs from it at runtime via `assay_values_for_outcome()` (tolerant of both rounded and unrounded 0.90×target thresholds).
- **CREDIT_HOLD is unreachable under a unique reading** (§3.4's auto-flip presupposes balance > limit; §3.8 rejects any registration that would push balance past the limit). The customer-status gating instances (`charge_create_gated_by_customer_status`, `business_safety_vs_business_fiscal_priority_on_charge_create`) are exercised through **CLOSED** customers, which §3.5 covers with the same `ERR_CUSTOMER_CREDIT_HOLD` (402).
- Initial `version == 1` is not PRD-stated → presence/type asserted instead; all OCC flows read versions from live responses.
- The `cylinder_capacity_circular...` and `retreat_order_cascades...` recipes contained setup-order bugs vs the PRD (loading while cylinder LOADED; ordering re-treat while last assay is PASS); setups were re-sequenced to satisfy PRD preconditions while preserving each instance's asserted claim.
- The nested-rounding divergence (per-piece-then-sum vs sum-then-round) is only observable at 4-decimal half-boundaries whose outcome depends on binary float representation → not uniquely derivable; the second test for that instance instead pins both rounding stages (provisional at cycle-complete, final at assay) on the recipe's 3-piece charge.
- `immutable_retention_assay_no_update_endpoint` asserts field absence (`version`/`updated_at`) plus a PUT probe accepting 404/405.

### Files
**test_helpers/** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/test_helpers/`):
`__init__.py` (barrel), `types.py` (10 status enums + 12 TypedDicts; append-only entities omit `updated_at`/`version`), `api_client.py` (44 endpoint methods), `api_errors.py` (45 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + append-only field assertions), `factories.py`, `constants.py` (fee schedule, species factors, hazard constants, round-half-up helper), `test_users.py` (6 opaque roles), `fixtures.py` (composite drivers: `setup_shop`, `setup_cycle_complete_charge`, `setup_assayed_charge`, `setup_tagged_charge`, `setup_released_charge`, `setup_closed_customer`, `drive_inspection_to_findings`, `drive_plant_score_to_zero`, plus PRD-pinned expectation calculators for provisional/final retention and registration fees).

**test_suite/** (`.../test_suite/`):
`conftest.py`, `test_01_registration_envelope_and_access.py` (10), `test_02_cylinder_capacity_and_slots.py` (10), `test_03_charge_composition.py` (5), `test_04_cycle_and_provisional.py` (9), `test_05_assay_and_retreat.py` (10), `test_06_drip_pad_and_hazard.py` (4), `test_07_tagging_and_release.py` (11), `test_08_customer_credit.py` (4), `test_09_inspections_and_governance.py` (5).

### Stage 2 self-check
- **Tag audit**: every one of the 70 tests carries exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line; all resolve to real yaml instances; none point at stubs. Coverage: all 19 difficulty instances ≥2 tests; all 31 translated corner instances ≥1 test. PASS.
- **Import audit**: all `from test_helpers import ...` names resolve in the barrel (one missing export, `piece_volume_cuft`, found and fixed); all fixture/helper callables resolve. PASS.
- **Citation audit**: every test docstring contains a ≥8-word verbatim substring that literal-greps against `workspace/PRD.md`, and asserted error IDs are named in PRD prose (§2.x/§3.x), not just the §5 table. PASS.

## Step 6: Generate implementation — 2026-08-12T23:45:00.000Z

Implementation complete. Summary:

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/workspace/implementation/`)

- `start.sh` — guarded launcher (`pip install` only if flask missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=2.2,<4
- `app.py` — Flask entry, blueprint registration, ApiError/404/405/500 envelope handlers
- `db.py` — in-memory store (empty dicts at boot, no seeding), frozen logical clock defaulting to 2026-08-01T00:00:00Z, UUID minting, `version`/`updated_at` touch, 3-fractional-digit ISO-8601 UTC timestamps
- `errors.py` — ApiError + all 42 catalog error IDs
- `response.py` — exact envelope: `meta{api_request_id (req_…), api_request_timestamp}`, `response_type` object/array/error, `data`; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (400 on missing/invalid incl. unknown role), per-endpoint role authorization (403)
- `util.py` — body shaping (ERR_INVALID_REQUEST/ERR_INVALID_ENUM before the cascade per PRD §2.9), timestamp parsing, pagination (limit default 10, clamped 1–100; offset ≥0; created_at-ASC + insertion-seq tiebreak), left-to-right nested path resolution with resource-specific 404s and parent scoping
- `calc.py` — all calculation rules with Decimal ROUND_HALF_UP
- `routes/` — plants, cylinders (+slots), preservatives, customers, charges, charge_children (pieces/assays/drip-logs/warranties), cycles, inspections, flat (flat GETs + reverse-reachability + filtered lists), admin (clock + force-state)

## Endpoint coverage
**96/96 unique routes** from PRD §4 implemented (scaffold's 3 duplicated route rows collapse to the same paths).

## Calculations / state machines / validation / OCC
- **Calculations**: provisional retention (per-piece species/incised factors, averaged, 3dp half-up after multiplication — verified 0.9×0.06 mix → 0.048); final retention (per-piece 4dp contributions then 3dp ratio); registration fee in pinned order base→volume discount (10/50 mbf tiers)→+18% custom uplift→term multiplier with per-step cent rounding (verified 3200→3040→4408); hazard liability ($2.50/L + $2500 surcharge >50L, score −50; scrap $750/mbf, score −100, clamped ≥0 — verified 265000/2250000); capacity check (==max allowed, verified); slot overlap (half-open effective intervals +buffer, adjacency allowed, past slots excluded — verified); assay outcome rule with inclusive boundaries (PASS/FAIL_MARGINAL/FAIL_GROSS verified)
- **State machines**: all 10 entity machines incl. cascades (revoke → cylinders DECOMMISSIONED + charges SCRAPPED; cycle complete → charge/pieces/provisional; assay → charge/pieces/final; order-retreat → warranties VOIDED_BY_RETREAT; warranty → release + customer debit + auto CREDIT_HOLD; close-FAIL at score ≤300 → auto-SUSPEND; stock-level auto transitions)
- **Validations**: full 19-priority cascade implemented in order, incl. licensing(4) before capacity(6)/slot(16)/credit(17)/retreat(18)/OCC(19); request shaping before the cascade per PRD §2.9
- **OCC**: `expected_charge_version` on order-retreat and warranty-registration; mismatch → `ERR_STALE_VERSION` 412, checked last (after credit) per priority 19 — verified

## Boot smoke test
`PORT=18923 bash start.sh` → HTTP ready in <2s, POST /treatment-plants 201 with correct envelope, unauthenticated GET → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, clock hook 200, clean SIGTERM shutdown. Three further live sessions exercised the full workflow (load→cycle→assay→drip→tag→warranty release), the FAIL_MARGINAL re-treat loop (RE_TREAT_PENDING → cycle_number 2 → IN_CYLINDER), suspend/reinstate gating, and error paths — all returned expected statuses/error IDs.

Notes on undocumented constants (chosen deterministic defaults; tests must read derived values like `target_retention_pcf` from responses since the spec fixes no numbers): retention targets UC3B/UC4A/UC4B/UC4C = 0.25/0.40/0.60/0.60 pcf (AWPA CCA values), low-stock threshold = 100 gal, cycle consumption estimate = 10 gal/mbf.

## Step 7: Run tests and iterate — 2026-08-13T00:20:00.000Z

All 8 rounds pass 70/70. The 37 stray `app.py` processes belong to other pipelines on this shared box (none from task_1332 — my sweep's servers were reaped by the runner). Work is complete.

## Summary

**Exit state: clean 8-round parallel sweep — all 8 rounds at 70/70 passed (~52s/round).**

**Iterations run:** 2 sweeps (16 round-runs total). Iteration 1: 3 distinct failures (1 deterministic + 2 infra-flaky). Iteration 2: zero failures across all 8 rounds.

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/test_suite/test_05_assay_and_retreat.py` — `test_retreat_branch_returns_charge_to_cylinder_with_next_cycle_number` (failed 8/8 rounds with `ERR_CYLINDER_NOT_LOADED`). STEP 2 test bug: the setup relied on the unassigned load slot (`charge_id=None`) to satisfy PRD §3.7's "a `TREATMENT` slot for it must exist" — a reading a faithful PRD-only implementer need not adopt, since §3.2 explicitly permits booking a slot whose `charge_id` references a `RE_TREAT_PENDING` charge (the mechanism that exists precisely for this path). Fixed the setup to book a charge-linked TREATMENT slot after ordering the re-treat (window 2026-08-13T06:00→2026-08-14T06:00, past the load slot's effective end 2026-08-13T00:29Z to respect the half-open-plus-buffer overlap rule of §3.2). The PRD-verbatim assertions (`cycle_number == 2`, charge → `IN_CYLINDER`) are unchanged, and the test now passes under both strict and lenient readings of "a slot for it". Also added `book_treatment_slot` to the imports.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/workspace/implementation/start.sh` — replaced the `python3 -c "import flask"` presence check with an `importlib.util.find_spec` check so a warm boot pays for exactly one Python+Flask import instead of two. This addresses the infra flakes (`test_provisional_rounds_once_after_multiplications` erroring at exactly the runner's 15s restart-poll window in 5/8 rounds, and one `Connection reset by peer`), which were caused by boot starvation under a concurrent 8-round sweep from a different task (task_1338) sharing the host. No implementation semantics changed; round wall time dropped from ~96–110s to ~52s.

**Notable diagnostic findings:** The `ERR_CYLINDER_NOT_LOADED` failure traced to `_find_charge_for_cycle` in `routes/cycles.py` requiring `slot.charge_id == charge.id` on the re-treat path while the load path accepts unassigned slots — a defensible strict reading kept as-is; the test was made reading-agnostic instead. No PRD-silence deletions were required; the two known generation gaps (assay marginal/gross boundary, low-stock threshold) remain intentionally untested.

(Orchestrator verification: all 8 `results.{1..8}.json` files independently re-read — every round passed=70 total=70 failed=0.)

## Step 8: Finalize PRD — 2026-08-13T00:30:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/workspace/PRD_FINALIZED.md` with exactly one inline revision.

## Summary

**Line counts / delta:** PRD.md = 366 lines, PRD_FINALIZED.md = 366 lines (0.0% line delta; the change is an in-place expansion of one sentence on line 192).

**Changes (1 total):**
- §3.7 — revise — the sentence "To run the re-treat, a `TREATMENT` slot for it must exist" now pins the strict reading the implementation chose: the slot must be booked on the cylinder where the new cycle is scheduled and its `charge_id` must reference the re-treated charge; an unassigned (`charge_id`-less) slot does not qualify. No window-coverage requirement was added (impl has none on this path — the fixed test's re-treat slot lies entirely in the future relative to the logical clock and passes), and no error code was pinned (PRD named none here; under-determined wording preferred since the Step 7 fix no longer exercises that error path) — `implementation/routes/cycles.py:48-59` (`_find_charge_for_cycle`, IDLE/re-treat branch: `s["cylinder_id"] == cyl["id"] and s["slot_kind"] == "TREATMENT" and s["charge_id"] == c["id"]`).

**Items producing no edit:** the `start.sh` change is pure launcher performance (importlib check) with zero behavioral semantics and no PRD counterpart — no edit. The two "known generation gaps" (assay marginal/gross boundary, low-stock threshold) are explicitly "intentionally untested" and are not fixes listed in the diff — out of hard scope, no edit.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) Subject: the TREATMENT-slot precondition for scheduling a re-treat cycle on a `RE_TREAT_PENDING` charge ("a slot for it must exist").
- (b) Impl paths enumerated and read: `implementation/routes/cycles.py` (`_find_charge_for_cycle` lines 32–67 — LOADED branch: no slot check; IDLE re-treat branch: charge-linked slot required, plant-wide charge search, no window check; IDLE residual post-abort branch: no slot check; both failure modes raise `ERR_CYLINDER_NOT_LOADED`); `implementation/routes/charges.py:85-99` (load path — accepts `charge_id is None` or matching, window must cover now; governed by §3.5, untouched); `implementation/routes/cylinders.py:121-174` (booking — `charge_id` may reference `STAGED`/`RE_TREAT_PENDING`, per §3.2; the satisfying mechanism), `cylinders.py:75-93` (mark-cleaned/decommission slot handling — unrelated to charge linkage), `cylinders.py:217-226` (cancellation), `implementation/routes/flat.py:144-149,366-371` (read-only slot listings), `implementation/routes/admin.py:15` (force-state can create `RE_TREAT_PENDING` charges, which then flow through the same `_find_charge_for_cycle` check); greps for `RE_TREAT_PENDING`, `slot`, `ERR_NO_SLOT_FOR_CHARGE`, `ERR_CYLINDER_NOT_LOADED` across all of `implementation/`.
- (c) Wording adjustments from the pre-edit search: scoped the pin with "booked on the cylinder where the new cycle is being scheduled" (impl requires the slot on the scheduling cylinder, while the charge search is plant-wide); added the parenthetical tying it to §3.2's booking permission against a `RE_TREAT_PENDING` charge (keeps §3.2 and §3.7 mutually coherent); deliberately omitted any time-window clause (impl's re-treat branch performs no window check, unlike the load path) and any error-code clause (PRD named none; impl's `ERR_CYLINDER_NOT_LOADED` is an artifact of its charge-discovery structure and the fixed test does not assert it); kept the sentence scoped to the re-treat so it makes no claim about the load path (§3.5, unassigned slots accepted), the LOADED-cylinder path, or the post-abort residual path.

## Step 9: Complete PRD — 2026-08-13T00:47:20.000Z

(Resume note: a prior Step 9 run was killed mid-flight — it left a `PRD_COMPLETED.md` byte-identical to `PRD_FINALIZED.md` with no worklog entry, i.e. the completeness scan never verifiably ran. The artifact was discarded and Step 9 re-run fresh. Verbatim summary of the re-run subagent follows.)

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1332_wood_treating_pressure_treatment_plant/workspace/PRD_COMPLETED.md`.

**Stats**
- Source: `PRD_FINALIZED.md` (366 lines, 57,552 chars) → `PRD_COMPLETED.md` (366 lines, 61,918 chars); char-delta **+4,366**. All edits inline; no sections added.
- Counts: **20 ambiguity-pins, 6 mismatch-revisions** (26 edited passages).

**Changes** (per-change bullets; `implementation/` prefix omitted from paths):

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to ≥0), non-integer values rejected `ERR_INVALID_REQUEST` (400) — util.py:119-140
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation (insertion) order — util.py:143-144
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — db.py:54-64
- §2.5 — revise — mismatch — the LICENSED-gated set is six operations, adding scheduling a treatment cycle and beginning an inspection to the previous four — routes/cycles.py:82-84, routes/inspections.py:86-87
- §2.9 — revise — ambiguity — request shaping (pre-cascade) also covers inverted/empty time ranges via `ERR_INVALID_TIME_RANGE` (400) — routes/cylinders.py:133-134, routes/inspections.py:49-50, routes/charge_children.py:173-175
- §2.10 — insert — ambiguity — all server-generated timestamps (`created_at`, `updated_at`, `api_request_timestamp`) read the logical clock; clock-set answers 200 with `current_utc`; invalid `target_status` rejected `ERR_INVALID_ENUM` (400) — db.py:50-51, response.py:15-19, routes/admin.py:26,33-34
- §3.1 — insert — ambiguity — suspend when neither warrant condition holds (or plant not LICENSED) rejected `ERR_INVALID_STATE` (409) — routes/plants.py:61-74
- §3.1 — revise — mismatch — reinstatement requires no inspection in an open state (CLOSED_PASS *or* CLOSED_FAIL acceptable), not "every open inspection reached CLOSED_PASS"; failure is `ERR_INVALID_STATE` (409) — routes/plants.py:85-94
- §3.1 — revise — ambiguity — revoke preconditions pinned (`ERR_INVALID_STATE` unless SUSPENDED at score 0); terminal charge states enumerated (RELEASED/REJECTED/SCRAPPED); revoke cascade also scraps non-RELEASED/non-SCRAPPED pieces — routes/plants.py:105-123
- §3.2 — revise — ambiguity — mark-cleaned removes each CLEANING slot whose `slot_end` lies beyond now — routes/cylinders.py:76-79
- §3.2 — insert — ambiguity — slot `charge_id` naming no existing charge rejected `ERR_CHARGE_NOT_FOUND` (404) — routes/cylinders.py:155-158
- §3.2 — insert — ambiguity — `from_iso`/`to_iso` filter semantics: `slot_start >= from_iso`, `slot_end <= to_iso` — routes/cylinders.py:187-192
- §3.3 — insert — ambiguity — the 0–100 bound applies to `min_working_assay_pct` and `new_assay_pct` too, `ERR_INVALID_REQUEST` (400) — routes/preservatives.py:23-25,36,67
- §3.3 — insert — ambiguity — low-stock threshold is 100 gallons — calc.py:48
- §3.3 — revise — mismatch — DEPLETED is reached from IN_STOCK or LOW_STOCK at exactly zero gallons (not only from LOW_STOCK) — calc.py:183-191
- §3.3 — insert — ambiguity — quarantine release with assay still below minimum rejected `ERR_ASSAY_BELOW_WORKING_MINIMUM` (422) — routes/preservatives.py:117-122
- §3.5 — revise — ambiguity — target retention lookup values pinned: 0.25 UC3B / 0.40 UC4A / 0.60 UC4B / 0.60 UC4C — calc.py:12-17
- §3.5 — revise — mismatch — load-time slot gate: window must cover the present moment (`slot_start <= now <= slot_end`), and a slot with absent `charge_id` qualifies for any charge (was "covers the requested treatment start through the estimated cycle", "charge_id matches") — routes/charges.py:90-99
- §3.5 — insert — ambiguity — unresolvable `customer_id` on a custom-treat charge rejected `ERR_CUSTOMER_NOT_FOUND` (404) — routes/charges.py:103-105
- §3.6 — revise — ambiguity — cycle scheduling: `preservative_id` unresolved → `ERR_PRESERVATIVE_NOT_FOUND` (404); cylinder neither LOADED nor IDLE → `ERR_CYLINDER_NOT_LOADED` (409); charge selection rule (LOADED → IN_CYLINDER charge present; IDLE → RE_TREAT_PENDING charge with referencing TREATMENT slot, else residual post-abort IN_CYLINDER charge); new cycle's `solution_assay_at_start_pct`/`abort_reason` sit null — routes/cycles.py:32-67,85-87,111-113
- §3.6 — insert — ambiguity — estimated consumption = charge `volume_mbf` × 10 gallons/mbf, inventory floors at zero — routes/cycles.py:186-188, calc.py:54
- §3.6 — insert — ambiguity — LOW_STOCK/DEPLETED concentrate at cycle start fails with `ERR_INVALID_STATE` (409) — routes/cycles.py:182-183
- §3.7 — insert — ambiguity — recording an assay against a charge not in CYCLE_COMPLETE rejected `ERR_INVALID_STATE` (409) — routes/charge_children.py:101-102
- §3.7 — revise — mismatch — no per-piece penetration is captured; `penetration_pct` stays at its initial 0 (was "captures the assay's penetration measurement") — routes/charge_children.py:126-134
- §3.7 — revise — mismatch — verdict rule rewritten to impl's total order: PASS if both bounds met; FAIL_GROSS if mean < threshold; FAIL_MARGINAL in every remaining case (PRD had left mean≥target-with-low-min and marginal-mean-with-ok-min unclassified) — calc.py:130-143
- §3.7 — revise — ambiguity — scrap permitted only from ASSAYED_FAIL or RE_TREAT_PENDING and only under the FAIL_GROSS/cycle_number≥3 conditions, else `ERR_INVALID_STATE` (409) — routes/charges.py:235-241
- §3.7 — revise — ambiguity — reject requires a CRITICAL inspection standing in FINDINGS_ISSUED citing the charge; violations `ERR_INVALID_STATE` (409); cylinder moves to NEEDS_CLEANING only when LOADED/CYCLE_RUNNING/DRAINING — routes/charges.py:209-225
- §3.8 — insert — ambiguity — incise rejected `ERR_INVALID_STATE` (409) when charge not STAGED/IN_CYLINDER, `requires_incising` false, or piece not RAW — routes/charge_children.py:72-77
- §3.8 — revise — ambiguity — the >50 L surcharge lands on top of the log's `liability_cents` (and thus the ledger addition) — calc.py:165-172, routes/charge_children.py:181-190
- §3.8 — revise — ambiguity — tag fails with `ERR_DRIP_PAD_CONTAINMENT_BREACH` when no drip log exists at all; the 24 h dwell is measured on the latest log — routes/charges.py:266-277
- §3.8 — revise — mismatch — warranties never lapse to LAPSED (impl has no lapse mechanism); ACTIVE ends only via VOIDED_BY_RETREAT — routes/charge_children.py (no lapse path)
- §3.9 — insert — ambiguity — inspection window is inclusive at both ends for begin — routes/inspections.py:90-92
- §3.9 — insert — ambiguity — close carries `outcome` of PASS/FAIL (CLOSED_PASS/CLOSED_FAIL spellings accepted), requires FINDINGS_ISSUED else `ERR_INVALID_STATE` (409), auto-suspends only while plant still LICENSED — routes/inspections.py:123-137

**Not changed (deliberately):** the §3.7 flavor claim that provisional/final diverge ≥0.05 pcf on FAIL_MARGINAL (non-normative observation, no API behavior prescribed); Flask catch-all 404/405/500 handlers and timestamp-parse leniency (outside the PRD's endpoint surface); nested-cylinder slot listing additionally accepting `charge_id` (superset of PRD-stated filters, not contradictory).
