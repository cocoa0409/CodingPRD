# Worklog — task_0817_weights_measures_device

## Step 1: Create task directory — 2026-07-10T08:01:25.524Z

Created `tasks/task_0817_weights_measures_device/` and `tasks/task_0817_weights_measures_device/workspace/` (pre-assigned directory, no index auto-scan).

## Step 2: Generate scaffold — 2026-07-10T08:26:00.000Z

All three artifacts are written, parse under `yaml.safe_load`, and pass `scaffold_lint.py` with `VERDICT: clean lint` (296 calls scanned, all 15 FKs reverse-reachable).

## Summary

Generated a fresh **Expert**-tier scaffold for `task_0817_weights_measures_device` purely from the scenario + skill spec (no sibling tasks consulted).

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0817_weights_measures_device/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (+ §1.2.1 concurrency)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts:**
- Endpoints: **34** (flat topology, `api_prefix: "/"`; 1 test-driving `/_clock/set_current_utc`)
- Entities: **11** (Establishment, Inspector, Device, Inspection, TestReading, ScannerAuditItem, Complaint, Seal, CondemnationOrder, Penalty, FeeInvoice)
- Errors: **29**
- Calculations: 6; State machines: 8; 1 concurrency rule (OCC on `Device.version` at `POST /inspections`)
- §1.8: **18 instances** (9 Difficulty Rules × 2)
- §1.9: **27 active instances + 5 `excluded_because` stubs** (32 total)

**Design character:** Compliance/audit archetype. Cyclic Device state machine (SEALED⇄CONDEMNED via re-test), branching Inspection finalize fork, two depth-3 cascades from distinct triggers (finalize-FAIL→condemn→penalty→balance; suspend→OOS→void-seal→count), dual-variant calcs on different domains (fee proration on FeeInvoice, acceptance-vs-maintenance tolerance on Device), combinatorial mode-(a) tiered tolerance + mode-(b) per-item penalty rounding, two temporal-overlap semantics (Inspector half-open adjacency vs Device 60-min buffer), and two conserved-quantity invariants (money balance, sealed-device count).

All formula-derived assert literals were computed in code (fees 6000/9000/15000/8000, penalties 151/5000/7500, balance 17000, tolerances) and match. No forbidden concurrency vocabulary present.

One note: endpoint count is 34, marginally above the Expert 20–32 guideline — the extra reads are the FK reverse-reachability GETs the lint requires; the guideline is explicitly soft and the surface stays tightly coupled rather than padded.

## Step 3: Copy shared files — 2026-07-10T08:27:07.190Z

Copied `./INSTRUCTION.md` → `tasks/task_0817_weights_measures_device/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-10T08:35:00.000Z

Generated `workspace/PRD.md`. **PRD line count:** 299. **Endpoints documented:** 34 (matches the scaffold exactly).

Structure: §1 Introduction (compliance/audit + ledger framing); §2 Global Specifications — 9 subsections: RBAC (all three roles), verbatim §2.2 response envelope, pagination, common properties/versioning (`TestReading`/`ScannerAuditItem` flagged `common_fields: false` — only `id`+`created_at`), amounts/rounding, OCC on inspection scheduling, nested-retrieval + validation ladder, cascading balance/sealed-count consistency, logical clock; §3 Business Logic — 9 scattered subsections (establishment sanctions, device registration + prorated fee, scheduling with ordered checks, conducting inspections, accuracy-tolerance evaluation, scanner audit, finalize PASS/FAIL fork with cascades and full penalty calculation, retirement + complaints, settlement); §4 endpoint table (34 rows); §5 error table (29 codes).

Hard Contract reports: Contract 1 (Field-Name Coverage) PASS — all 44 field identifiers verbatim in backticks; all enums, states, roles present. Contract 2 (Rule Coverage) PASS — validation priority as explicit ladder; concurrency rule via `expected_device_version` + `ERR_STALE_DEVICE_VERSION` (412); all state transitions, cross-entity cascades (seal void, sealed-count adjust, condemnation-order lift, penalty creation + balance recompute), all six calculations rendered in non-pseudocode prose. Contract 3 (§3 Path Purity) PASS — 0 path/method tokens in §3.

Under-specified point noted by generator: scaffold gives no explicit mapping for `violation_type` enum value `OPERATING_CONDEMNED`. Documented reading: `PRICE_ERROR` for failing price verification, `OUT_OF_TOLERANCE` for failing accuracy/complaint re-test, `OPERATING_CONDEMNED` when the failing inspection targets a device already `CONDEMNED`.

## Step 5: Generate unit tests — 2026-07-10T09:00:00.000Z

All checks pass: 63 tests collect cleanly, no unused imports, no scaffold/table leakage in generated code, every PRD citation verified against a literal grep of PRD.md.

**Files written**

`test_helpers/`: `__init__.py` (barrel export), `types.py` (11 status enums, role enum, entity TypedDicts — append-only `TestReading`/`ScannerAuditItem` correctly omit `updated_at`/`version` per PRD §2.4), `api_client.py` (`ApiClient(GenericApiClient)`, one method per endpoint, 34 methods incl. `_clock`), `api_errors.py` (`ApiErrorId` enum, 29 errors + HTTP status map), `assertions.py` (per-entity assertions + append-only checkers + balance helper), `factories.py` (input-field-only payload factories, unique badge/serial generation), `constants.py` (fee/tolerance/penalty/buffer constants), `test_users.py` (shared role headers + `make_<role>_headers` builders with entity-backed identity threading), `fixtures.py` (`accuracy_pass_seal`, `accuracy_fail_condemn`, `in_progress_accuracy`, `in_progress_price`, reverse-lookup readers, `bootstrap_est_inspector`).

`test_suite/`: `conftest.py` + 7 domain test files (`test_01`–`test_07`).

**Tests emitted: 63** — Queue A (Difficulty): all 18 instances × exactly 2 tests = 36. Queue B (Corner): all 27 non-stub instances × 1 test = 27. Every docstring carries a verbatim PRD citation plus exactly one `Design:` tag resolving to a real instance.

**Instances skipped: none of the translatable ones.** All 18 difficulty + 27 corner non-stub instances passed the PRD-first two-condition filter. The 5 `errors`-section corner entries are `excluded_because:` stubs — not translated per spec; all 5 `difficulty_instance` cross-references verified to resolve.

**Notable adjudication calls**: the two validation-priority instances (`state_beats_temporal`, `referential_beats_temporal`) were kept, not skipped — PRD §3.3 gives an explicit numbered ordering, so precedence is uniquely derivable. `occ_schedule_correct_version_succeeds_and_bumps` asserts device version incremented by exactly 1 (PRD §3.3) rather than hard-coding `== 2`, since PRD §2.4 does not pin the initial version value.

## Step 6: Generate implementation — 2026-07-10T09:00:00.000Z

**Files written** (under `workspace/implementation/`): `start.sh` (foreground launcher, `exec python3 app.py`, guarded `pip install`, binds `0.0.0.0:$PORT`, default 10000), `requirements.txt`, `app.py` (app factory, blueprint registration, ApiError/404/405/500 handlers, `Flask(static_folder=None)`), `core.py` (in-memory `Store` singleton — empty on boot, **no seeding**; logical clock default `2026-03-01T00:00:00Z`; UUID/timestamp helpers; response envelope; auth via `X-User-ID`/`X-User-Role`; pagination; serialization), `services.py` (all 6 calculations — registration_fee proration, accuracy_tolerance acceptance-vs-maintenance, scanner_audit, penalty_amount with per-item→sum→multiply rounding via `Decimal`+`ROUND_HALF_UP`; balance/sealed-count recompute; seal/condemn cascades), `lookups.py` (entity fetch helpers raising correct per-entity 404 error IDs), and 10 route modules (establishments, inspectors, devices, inspections, complaints, seals, condemnations, penalties, fee_invoices, clock).

**Registered route count: 34** (exactly matches scaffold endpoint table; verified via `app.url_map.iter_rules()`). All 14 `.py` files pass `ast.parse`. `bash start.sh` boots cleanly — authenticated `GET /devices` → 200, unauthenticated → 401.

Behavior verified end-to-end via curl: envelope, pagination, ISO8601-with-millis timestamps, logical clock; registration fee proration (SCANNER 15000×0.5=7500 in Q3, `proration_applied=true`) and balance recompute; inspection lifecycle (schedule with OCC device-version bump, stale → 412; start; readings/audit-items; finalize); accuracy tolerance acceptance (REGISTERED, tighter maint/2) vs maintenance (in-service); sealing (sequential `seal_number`, `sealed_device_count`++); condemnation + penalty (OUT_OF_TOLERANCE 5000), seal VOIDED on fail; PRICE_ERROR per-item math (150+300=450); OPERATING_CONDEMNED on already-condemned device; repeat-multiplier keyed on strictly-earlier `created_at`; suspend requires balance > 0, cascade to OUT_OF_SERVICE/VOIDED, reinstate requires zero balance (409→200 after payment); ownership: wrong-establishment pay → 403, owner → 200.

Judgment call noted: recording readings/audit-items requires the inspection to be `IN_PROGRESS` (returns `ERR_INSPECTION_NOT_IN_PROGRESS` otherwise), matching PRD §3.4's "while an inspection is IN_PROGRESS" framing; scaffold defines no explicit error for that state.

Orchestrator verification: 34 Flask routes registered, `app.py` present, all 14 modules `ast.parse` clean, 63 `def test_` functions across 7 files.

## Step 7: Run tests and iterate — 2026-07-10T09:20:00.000Z

All 8 rounds pass 63/63. Clean sweep.

## Summary

**Iterations run:** 2 (1 diagnostic sweep + 1 verification sweep).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services.py`, `repeat_multiplier()` (and its caller `compute_penalty_amount()` / `finalize_fail()`): changed the "prior condemnation" ordering test from comparing only `created_at` strings to comparing the tuple `(created_at, _seq)`.

**Root cause:** The single consistent failure across all 8 initial rounds was `test_second_condemnation_applies_repeat_multiplier_1_5` (`assert 5000 == 7500`). PRD §3.7 (line 203) states the repeat-offense multiplier counts "the condemnation orders belonging to any device of this establishment whose `created_at` is strictly earlier than this new order's `created_at`" — 1.5x when there are one or two priors. The test condemns two devices of the same establishment in succession and expects the second penalty to be `round(5000 * 1.5) = 7500`.

The implementation mints `created_at` from a frozen logical clock (`store.clock`, advanced only via `/_clock/set_current_utc`, which the helper chain for this flow never calls). Both condemnation orders therefore received an identical `created_at`, so the strict `<` comparison found 0 priors → multiplier 1.0 → 5000. This is an implementation modeling artifact, not a PRD-faithful outcome: PRD models `created_at` as a real creation timestamp reflecting creation order. The codebase already uses `_seq` (a monotonic creation counter) as the authoritative tiebreaker for ordered listings (`core.py:255` sorts by `(created_at, _seq)`). Applying the same tiebreaker in `repeat_multiplier` makes "strictly earlier" resolve by true creation order when `created_at` ties, yielding 1 prior → 1.5x → 7500, consistent with PRD intent, and it is collision-free (robust against millisecond ties too). No PRD-untraceable behavior, endpoints, fields, or seeding were introduced; storage remains in-memory only.

Orchestrator verification: results.1–8.json all report `passed=63 total=63 failed=0 errors=0`.

## Step 8: Finalize PRD — 2026-07-10T09:30:00.000Z

Done. PRD_FINALIZED.md written with a single minimal edit.

**Line counts:** PRD.md = 299 lines; PRD_FINALIZED.md = 299 lines (both single-line-per-paragraph; the edit expanded line 203 in place, +0 lines, ~+3.3% words on that paragraph). Delta: 1 paragraph revised, 0 sections added.

**Change:**
- §3.7 "Penalty amount" (line 203) — *revise* — added a same-`created_at` tiebreaker: when two condemnation orders share an identical `created_at` (routine, because `created_at` is minted from the frozen logical clock of §2.9), ties are broken by actual creation order, so any condemnation order that already existed when the new order was created counts toward the repeat-offense history — matches `services.py:147-165` `repeat_multiplier()` comparing `(created_at, _seq)`.

**Why it was pinned (PRD-silence, not fixture bug):** PRD §3.7 as written counts priors on `created_at` strictly earlier only, and §2.9 mandates a frozen logical clock. A fresh implementer following both would give successively-condemned devices identical `created_at` → 0 priors → 1.0x, diverging from `implementation/` (which uses `_seq` to resolve the tie → 1 prior → 1.5x). The PRD did not uniquely determine tie behavior; the edit pins the implementation's choice.

**Per-edit pre-edit search log:**
- **(a) Subject:** ordering/tiebreaking of "strictly earlier than `created_at`" when counting prior condemnation orders for the repeat-offense multiplier.
- **(b) Impl paths enumerated & read:**
  - `services.py:147-165` `repeat_multiplier()` — edit site; tuple compare `(created_at, _seq) < key`.
  - `services.py:168-179` `compute_penalty_amount()` and `services.py:234-269` `finalize_fail()` — callers; `order` is the just-minted CondemnationOrder (max `_seq`), so tiebreak ⇒ all pre-existing establishment orders count.
  - `core.py:254-255` `sort_by_created()` — parallel `(created_at, _seq)` sort backing §2.3 list ordering; confirmed consistent, left unedited (out of scope).
  - `core.py:276-295` `base_common()` / `base_line_item()` — both stamp `_seq = store.next_seq()`, a global monotonic creation counter ⇒ `_seq` order == true creation order.
  - `core.py:52-53` `now()` + §2.9 — `created_at` sourced from frozen logical clock, establishing that identical `created_at` values are the normal case (the reason the tiebreaker is load-bearing).
- **(c) Wording adjustment:** phrased the tiebreaker as "actual creation order" rather than naming `_seq` (an internal field) and added the "already existed at the moment this new order was created" restatement to keep it consistent with the caller path (new order always highest `_seq`). Explicitly scoped the clause to the prior-condemnation count so it does not restate or narrow the §2.3 list-sort tiebreaker, which I left untouched.

## Step 9: Complete PRD — 2026-07-10T09:40:00.000Z

All 9 edits applied cleanly as in-paragraph inserts/revisions (no new sections, no line-count change).

**Source vs completed:** `PRD_FINALIZED.md` = 299 lines / 39,706 chars; `PRD_COMPLETED.md` = 299 lines / 41,169 chars; **char delta +1,463**. All changes are inline (line count unchanged).

**Counts:** ambiguity-pins = 6, mismatch-revisions = 3.

**Changes:**
- §2.3 Pagination — insert — ambiguity — PRD said `limit` "must be 1..100" without saying what happens on violation; pinned that out-of-range/unparseable `limit`/`offset` are silently clamped/defaulted, not rejected — `core.py:226-243`
- §2.3 Pagination — insert — ambiguity — pinned that list results with identical `created_at` are tie-broken by creation sequence (earliest first) — `core.py:255` (`sort_by_created` uses `(created_at, _seq)`)
- §2.4 Common Properties — revise — ambiguity — "starts at its initial value" replaced with "starts at 1" — `core.py:283` (`base_common` sets `version: 1`)
- §3.1 Sanctions (suspend) — insert — ambiguity — pinned that the positive-balance check is the sole precondition; server does not verify the establishment is currently `ACTIVE` — `routes_establishments.py:38-41` (no source-state guard)
- §3.1 Sanctions (reinstate) — insert — ambiguity — pinned that only the zero-balance check is enforced; current status not otherwise verified — `routes_establishments.py:57-60`
- §3.1 Inspectors — revise — mismatch — "a unique `badge_number`" changed to note the server records it as supplied and does **not** enforce uniqueness — `routes_inspectors.py:11-18` (no uniqueness check)
- §3.4 Starting an Inspection — insert — mismatch/silence — pinned that starting a non-`SCHEDULED` inspection is rejected with `ERR_INSPECTION_NOT_IN_PROGRESS`, and that this state check precedes the device-testability check — `routes_inspections.py:158-164`
- §3.7 Pass branch (Seal) — insert — ambiguity — pinned `seal_number` shape as the string `SEAL-000001` (zero-padded 6 digits, globally sequential) — `core.py:44-46` (`next_seal_number` → `"SEAL-%06d"`)
- §3.8 Complaints (resolve) — insert — silence — pinned that only a `FILED` complaint may be resolved; resolving an already-resolved one yields `ERR_INVALID_STATE` — `routes_complaints.py:57-58`
- §3.9 Waiving — insert — silence — pinned that a non-`ASSESSED` penalty cannot be waived and yields `ERR_PENALTY_NOT_PAYABLE` (PRD had only specified this error for *pay*, not *waive*) — `routes_penalties.py:57-58`

Behaviors confirmed already uniquely pinned (no change needed): the §3.3 scheduling check ordering, half-open inspector-overlap and 60-minute device-buffer logic, tolerance tiers/acceptance-halving (§3.5), scanner mispriced-count > 2 (§3.6), penalty rounding order and repeat-multiplier tie-break by creation order (§3.7), balance/sealed-count recomputation (§2.8), fee proration by logical-clock quarter (§3.2), and all default values (`device_class`→CLASS_III, `region`→UNASSIGNED).
