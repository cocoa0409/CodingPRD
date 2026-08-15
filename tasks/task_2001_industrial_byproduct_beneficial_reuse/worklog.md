# Worklog — task_2001_industrial_byproduct_beneficial_reuse

## Step 1: Create Task Directory — 2026-08-15T06:02:00.000Z

Pre-created by pipeline entry: `tasks/task_2001_industrial_byproduct_beneficial_reuse/` and `workspace/` already existed; no index scan performed per instructions.

## Step 2: Generate Scaffold — 2026-08-15T06:34:00.000Z

Scaffold generation complete and lint-clean. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2001_industrial_byproduct_beneficial_reuse/`, generated purely from the scenario text plus the skill spec (no sibling tasks were inspected).

**Domain design**: Industrial byproduct brokerage — primary archetype *compliance/audit* (permit + eligibility gating) with secondary *quota/allocation* (monthly committed tonnage, storage capacity); flat entity topology, cyclic state machines, segregation-of-duties role model, immediate consistency, and a logical clock (`POST /api/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`).

**SCAFFOLD.yaml** (§1.0–§1.7, fixed response envelope verbatim):
- **13 entities**: Generator, Offtaker, ByproductStream, CharacterizationProfile, ReuseEligibility, StatePermit, SupplyAgreement, OfftakeCommitment, Shipment, StorageFacility, StorageReservation, MarketPriceIndex (append-only, `common_fields: false`), SustainabilityCreditEntry (append-only)
- **8 state machines + 1 OCC concurrency rule**: Shipment is cyclic (DELIVERED→REJECTED→RECONDITIONING→DELIVERED); ReuseEligibility has deny→revise and suspend→reinstate loops plus lazy EXPIRED; OCC guards `POST /api/shipments` via `expected_supply_agreement_version` (412)
- **8 calculations**: tiered freight with share cap, provisional/final settlement with pinned rounding order (round tons to 3dp before money; residual to broker), index-price selector (effective_from DESC, `created_at` tie-break — never id), standard-vs-attested credit variants (1.0 ledger vs 0.92 attested factor), inclusive credit-tier thresholds (100/250), lazy monthly counter rollover (no version bump), strict-greater rejection tolerance (20%), per-day aggregate storage capacity over half-open windows
- **27 validation rows** (auth → ownership/segregation → request shape → existence → OCC → state → safety → temporal → constraint → referential → fiscal), **63 endpoints**, **26 error codes** (all referenced and all exercised), **5 roles** (Generator/Offtaker entity-backed; BrokerOps/ComplianceOfficer/PlatformAdmin opaque; eligibility approver must differ from filer)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances, 2 per rule × 9 rules, each with fully structured setup chains — highlights: provisional 6000 vs final 7000 on index move; standard 60.0 vs attested 55.2 credits; freight cap bind (93500→60000); rounding trap 17396 vs wrong-order 17395; depth-3 accept cascade (shipment→credit entry→total_credits→tier SILVER at 105.0); depth-3 reject cascade (20.5 > 20.0 tolerance → commitment auto-suspend → BOOKED siblings cancelled, DISPATCHED untouched); state-vs-fiscal and safety-vs-temporal priority conflicts; exact-boundary tonnage (100 == committed OK) and moisture (12.0 = max+2.0 accepted, 12.1 rejected); storage aggregate-capacity vs eligibility half-open-adjacency overlap semantics; inventory and credit-balance compensation invariants.

**SCAFFOLD_CORNER_DESIGN.yaml**: 45 instances (43 active + 2 `excluded_because` stubs) across all nine claim-extraction sections — entities (creation/defaults/not-found/required/enum/computed-ignored/immutability/pagination), state machines (invalid transitions, terminal lockdowns, idempotent-accept, bubble-ups, tolerance equality), calculations (tier-1-only freight 51000, latest-effective selector 350, acceptance-price fallback 500, GOLD at exactly 250, MET at exactly 100), validations (16 error-trigger instances covering every remaining error code), RBAC denials, envelope shape, OCC stale/correct version, month-rollover quota reset, and immediate-consistency read-your-write.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (716 calls scanned: 18 difficulty + 43 corner instances, 63 endpoints, 13 entities). Additional scripted checks: zero duplicate instance names across the union, all `grounds:` references resolve, all 26 errors referenced and exercised, enum closure holds (computed enums produced by calculations). All formula-derived assert literals were pre-computed with Python (Decimal, round_half_up) before being written.

## Step 3: Copy Shared Files — 2026-08-15T06:36:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2001_industrial_byproduct_beneficial_reuse/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: Generate PRD — 2026-08-15T06:45:00.000Z

The PRD is generated and fully verified. Final summary:

**Output**: `workspace/PRD.md` — 299 lines.

### Section List
- **§1. Introduction** (2 paragraphs — business context + system scope)
- **§2. Global Specifications & System-Wide Principles**: 2.1 RBAC / 2.2 API Response Structure (verbatim) / 2.3 Pagination / 2.4 The Logical Clock and Time-Driven Reconciliation / 2.5 Common Resource Properties / 2.6 Hierarchical Consistency and Cascading Mutations / 2.7 Nested Resource Retrieval / 2.8 Units, Precision, and Rounding / 2.9 Optimistic Concurrency Control / 2.10 The Validation Pipeline
- **§3. Business Logic & Workflows** (8 subsections, lifecycle-ordered): 3.1 Onboarding & Characterization / 3.2 Reuse Eligibility & State Permitting / 3.3 Supply Agreements & Offtake Commitments / 3.4 Booking: Freight, Quotas, Provisional Pricing / 3.5 Dispatch, Delivery & Acceptance Settlement / 3.6 Rejection, Reconditioning, Disposal, Cancellation & Voiding / 3.7 Buffer Storage / 3.8 Market Pricing & Sustainability Credit Reporting
- **§4. Endpoint Definitions** (63 rows, 4 columns), **§5. Error Code Catalogue** (26 rows, 2 columns)

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body: 52 required, 52 present, 0 missing
- endpoints[].query_params: 13 required, 13 present, 0 missing
- (also verified: 26/26 error IDs in §2/§3 prose; 42/42 enum & state values present)
Status: PASS

Rule coverage check:
- validations[] priority ordering: 13 priority tiers expressed as an explicit ordered pipeline in §2.10 ("earlier failure masks later checks"), 0 missing
- concurrency_rules[] OCC: 1 checked, 1 expressed (booking endpoint + expected_supply_agreement_version non-optional + ERR_STALE_AGREEMENT_VERSION/412; stale-view framing, no race language; "no other endpoint accepts a version field" stated), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed (from/to pairs, preconditions paired with error IDs, all side effects incl. bubble-ups, auto-suspend cascade, cyclic redeliver loop), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (freight tiers 15000/450/320/210/60000; provisional vs final settlement pinned 7-step order; price selection with created_at tie-break and acceptance fallback; standard 1.0 vs attested 0.92 credit variants; tier thresholds 250/100 inclusive; lazy rollover without version bump; 0.20 rejection tolerance strictly-greater; per-day half-open storage capacity with equality allowed and adjacency rule), 0 missing
- validations[] conditions: 22 checked, 22 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 63 endpoints checked; all side effects narrated; all multi-endpoint scopes enumerated (e.g., agreement/commitment-active on booking AND dispatch; window-overlap on submit/approve/reinstate; duplicate-permit on create AND activate; ERR_STREAM_NOT_CHARACTERIZED on filing + both activations), 0 missing
- entities[].fields[] structured content: 82 checked — types, defaults, null-until-set fields, and constraint ranges (revenue share strictly 0–1, freight share 0–1 inclusive, positive/non-negative bounds, date-ordering constraints) all reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (approve/deny, suspend/reinstate, terminate×3 states on both contracts, reject-cascade branches, lazy EXPIRED from APPROVED+SUSPENDED, standard/attested variants, provisional/final variants, storage check-in/release/cancel), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 444
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: §2.2 byte-identical to `section-2.2-response-structure.md` (diff-verified); §4 table 63/63 endpoints with roles matching scaffold ("All roles" for the five-role GETs); §5 26/26 error rows with matching HTTP statuses; zero fuzzy words and zero pseudocode operators outside the verbatim JSON block.

### Zero-Silence Rule Coverage Audit
All nine scaffold sections verified covered: `scenario` → §1; `response_envelope` → §2.2 verbatim + §2.3 (defaults 10/0, min 1, max 100, created_at ascending, meta fields); `entities` (13 entities/82 fields, incl. common_fields:false note for MarketPriceIndex/SustainabilityCreditEntry carrying only id+created_at) → §2.5 + §3; `state_machines` (10 machines incl. lazy EXPIRED and rollover semantics) → §2.4 + §3.1–3.7; `concurrency_rules` → §2.9/§3.4; `calculations` (7 rules, all constants embedded in business context) → §3.4–3.8 + §2.4; `validations` (priorities 1–13) → §2.10 + workflow-proximate error mentions; `endpoints` (63, incl. clock default 2026-08-01T00:00:00Z and no-wall-clock rule) → §4 + §3 side effects; `errors` (26) → §5 + scattered triggers; `roles` (5, with per-role identity prose — entity-backed Generator/Offtaker, opaque BrokerOps/ComplianceOfficer/PlatformAdmin) → §2.1.

### Ambiguity Adjudications
1. **Permit activation duplicate scope**: state-machine precondition says "no other ACTIVE permit" while validation priority 11 says "{FILED, ACTIVE}" for both create and activate. Rendered the stricter validation row for both operations (it subsumes the weaker row, since creation already prevents two FILED permits per pair).
2. **Shipment-action ownership**: scaffold annotates ownership only on creation endpoints; validation 3 covers "Generator/Offtaker write endpoints" generally. Generalized in §2.1: Generators act on shipments via their own agreements, Offtakers via their own commitments.
3. **Date-shape violations without a dedicated error** (valid_until after valid_from, expires_on on/after issued_on, term_end on/after term_start): attributed to the priority-4 well-formedness check (ERR_INVALID_REQUEST); reservation window shape explicitly maps to ERR_RESERVATION_WINDOW_INVALID per its validation row.
4. **counter_month before activation**: expressed as stamped at activation (counters zero, fulfillment_status UNMET from creation), matching the scaffold's activation side effect.
5. **Eligibility window adjacency**: stated that boundary-touching windows do not overlap — a direct consequence of the scaffold's half-open window specification, made explicit for reader clarity.

## Step 5: Generate Unit Tests — 2026-08-15T07:06:00.000Z

Generation complete. All artifacts are in place and audited.

**Files generated** (under `tasks/task_2001_industrial_byproduct_beneficial_reuse/`):

- `test_helpers/` — 9 files: `types.py` (12 entity TypedDicts with `common_fields` branching — MarketPriceIndex/SustainabilityCreditEntry omit `updated_at`/`version`; 15 status/role enums), `api_client.py` (63 endpoint methods, one per PRD §4 row), `api_errors.py` (26 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (12 entity assertions + freight-split invariant), `factories.py` (13 payload factories, input fields only), `constants.py` (freight tiers, 2.0 moisture tolerance, 0.92 attested factor, 100/250 tier thresholds, 0.20 rejection tolerance, default clock), `test_users.py` (shared opaque-role constants + mandatory per-instance builders for entity-backed Generator/Offtaker), `fixtures.py` (5 tiers: single creators → characterized stream → booking-ready/dispatch-ready chains → lifecycle shortcuts through accept → storage), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 9 numbered test files.

**Test counts:** 79 total — Queue A (Difficulty): 36 tests (18 instances × 2); Queue B (Corner): 43 tests (43 non-stub instances × 1).

**Instance coverage audit:**
- Difficulty: 18/18 instances translated, each with exactly 2 tests. 0 skipped.
- Corner: 43/43 non-stub instances translated. 0 skipped. Both stubs (`booking_blocked_when_agreement_suspended`, `credit_summary_computed_read`) left untranslated; their `difficulty_instance` cross-references verified to resolve.
- No instance failed the PRD-first filter — every asserted rule (including both priority-pair orderings, via the explicit pipeline stages in PRD §2.10) has verbatim PRD coverage with a uniquely derivable outcome.

**Two judgment calls logged:**
1. `create_generator_returns_201_with_defaults` — the recipe's literal `version == 1` sub-assertion is not uniquely derivable (PRD §2.5 never pins the initial version value; a PRD-only reader could start at 0). Test asserts presence/integer type plus all covered claims (201, UUID, `total_credits == 0.0`, `credit_tier == STANDARD`); the rest of the instance is fully translated.
2. `eligibility_window_half_open_exclusivity` — the recipe omits that D1's window `[2026-01-01, 2026-07-01)` cannot be approved at the default 2026-08-01 clock (PRD §3.2 `ERR_ELIGIBILITY_WINDOW_PAST`). Repaired by setting the logical clock to 2026-06-01 at setup; no asserted outcome changed.

**Audit results:**
- Design-tag audit: 79/79 tests carry exactly one `Design:` line as the final docstring line; all resolve to real instances; 0 untagged / 0 dual-tagged / 0 dangling; stubs have no tests.
- PRD citation: 117 quoted spans across all docstrings verified verbatim against `workspace/PRD.md` (normalized whitespace grep), 0 failures.
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; identity threading uses per-instance entity-backed headers throughout.
- `pytest --collect-only`: 79 tests collected cleanly; pyflakes clean; every pinned numeric (freight tiers/cap, 3dp-round-before-money order, credit variants, tolerance boundaries) independently recomputed per PRD formulas and matched.

## Step 6: Generate Implementation — 2026-08-15T07:06:00.000Z

Done. The implementation is complete and smoke-tested.

**Files created** under `workspace/implementation/`:

- `start.sh` — executable launcher; guarded dependency install (`python3 -c "import flask"` check, so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — app factory, `ApiError`/404 envelope handlers, blueprint registration
- `store.py` — in-memory store, **starts empty every boot** (no seeding); logical clock defaults to exactly `2026-08-01T00:00:00Z`
- `common.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in meta for lists), error envelope, `X-User-ID`/`X-User-Role` auth, body validators, `limit`/`offset` pagination (default 10, clamp 1–100), serialization
- `logic.py` — logical clock, lazy monthly rollover (no version/`updated_at` bump), lazy EXPIRED (with bump), price selection, freight tiers, credit recompute + tier, overlap helpers, `Decimal`/`ROUND_HALF_UP` rounding
- `routes/{orgs,streams,permits,agreements,shipments,storage,misc}.py`

**Endpoints: 63 implemented** — matches the scaffold endpoint table exactly (orgs 5, streams/characterizations/determinations 15, permits 4, agreements+commitments 13, shipments 13, storage 8, misc/clock 5).

**Calculation coverage:** freight_cost_allocation (tiered 15000/450/320/210 + 60000-cent cap on the generator share), shipment_settlement provisional and final (pinned 7-step order, 3-dp half-up tons, integer cents, broker residual absorbs rounding, pickup-price fallback at acceptance), market_price_selection (effective_from DESC, created_at DESC tiebreak; `ERR_PRICE_INDEX_GAP` at booking only), sustainability credits standard (ledger, factor 1.0) vs attested (shipments still ACCEPTED, factor 0.92, voided excluded), credit tiers (>=250 GOLD / >=100 SILVER, inclusive), monthly_counter_rollover (lazy, `cumulative_rejected_tons` exempt), rejection_tolerance_posture (strictly-greater vs `round_half_up(committed*0.20, 3)`), storage_overlap_capacity (per-day half-open intervals, equality allowed, adjacency not overlap).

**State-machine coverage:** all 8 machines, including characterization→stream and determination→stream bubble-ups, DENIED→DRAFT revise loop, APPROVED↔SUSPENDED, lazy EXPIRED for determinations (`>= valid_until`) and permits (`> expires_on`), commitment auto-suspension cascade cancelling BOOKED siblings with per-agreement quota release and version bumps, shipment RECONDITIONING loop, VOIDED reversal unwind, and the 13-stage validation pipeline with exact error IDs/HTTP statuses, OCC (`expected_supply_agreement_version` → 412), segregation of duties, and entity-backed ownership.

**Smoke-test result:** server boots cleanly via `bash start.sh` from a fresh process (verified twice: empty store, `total_count: 0`, clock at default month) and full request round-trips pass. Three ad-hoc suites ran green: (1) happy-path end-to-end with exact freight (76000/38000/38000), provisional (168000), and settlement (net 39.6 t, gross 166320, shares 99792/66528, payout 61792) assertions, credit accrual/summary, void unwind, storage check-in, lazy EXPIRED after clock advance; (2) tolerance cascade incl. exact-equality non-suspension at 20.000, auto-suspend at 30, sibling auto-cancel version/quota effects, rollover without version bump, window adjacency vs overlap, deny/revise; (3) error paths across 400/401/403/404/409/412/422 including pipeline-order cases (ownership before FK, quality gate leaving shipment DELIVERED) and pagination clamping.

## Step 7: Run Tests and Iterate — 2026-08-15T07:12:00.000Z

All 8 rounds of the parallel stability sweep passed cleanly on the first iteration — 79/79 tests in every round, 0 failures, 0 errors, 0 skipped. No flakiness surfaced across the concurrent sweep under per-test-server isolation.

## Summary

- **Iterations run**: 1 (clean 8-round parallel sweep, no fixes required)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `test_suite/`**: none
- **Fixes applied to `implementation/`**: none

The prior pipeline steps (documented in `tasks/task_2001_industrial_byproduct_beneficial_reuse/worklog.md`) produced a PRD, test suite (79 tests: 36 difficulty + 43 corner), and implementation that are mutually consistent and stable. The 8-round sweep at ~108s per round confirmed deterministic behavior with no timing-sensitive or ordering-sensitive failures.

## Step 8: Finalize PRD — 2026-08-15T07:12:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determines every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-15T07:25:00.000Z

All edits are in place and coherent. Final verification complete.

**Files**
- Source: `workspace/PRD.md` — 298 lines, 50,898 chars (no PRD_FINALIZED.md existed; Step 8 was skipped)
- Produced: `workspace/PRD_COMPLETED.md` — 299 lines, 54,586 chars
- Char delta: **+3,688 chars** across 21 diff hunks (20 in-place paragraph revisions + 1 inserted bullet line); no sections added or removed.

**Counts**
- Ambiguity-pins (PRD silent → inserted impl behavior): **15**
- Mismatch-revisions (PRD described different behavior → revised to impl): **6**

**Changes** (one bullet each; sections refer to PRD structure)

- §2.1 — insert — ambiguity — pinned that shipment-level ownership resolves through referenced commercial records: Generator side via the supply agreement's `generator_id` (named by `supply_agreement_id` at booking; via the shipment for dispatch/recondition/redeliver/dispose/cancel), Offtaker side via the commitment's `offtaker_id` (deliver/accept/reject) — `implementation/routes/shipments.py:39-48, 59-65`
- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + twenty random alphanumeric characters — `implementation/common.py:33-34`
- §2.2 — insert — ambiguity — undefined paths are rejected with 404 `ERR_NOT_FOUND` in the standard error envelope — `implementation/app.py:28-31`
- §2.3 — insert — ambiguity — pagination: out-of-range integer `limit` clamped to [1,100] and negative `offset` clamped to 0 (not rejected); non-integer values yield `ERR_INVALID_REQUEST`; `has_more` defined as `offset + returned items < total_count`; sort ties on identical `created_at` broken by insertion order — `implementation/common.py:179-206`, `implementation/logic.py:79-80`
- §2.4 — revise — mismatch — clock endpoint: "advances" replaced with "sets" (backward setting allowed, no monotonicity); accepts full ISO datetimes (naive read as UTC) or bare ISO dates (midnight UTC); unparseable → `ERR_INVALID_REQUEST`; `current_utc` echoes the supplied `to_iso8601` string verbatim — `implementation/routes/misc.py:108-131`
- §2.4 — insert — ambiguity — monthly rollover also resets an agreement's `fulfillment_status` to `UNMET` in the same touch-free refresh — `implementation/logic.py:87-95`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/logic.py:64-67`
- §2.7 — revise — mismatch — replaced "the parent must exist before any child payload is considered" with the impl's pipeline reality: ownership scoping (stage 3) and child-payload well-formedness (stage 4) precede parent existence (stage 5), so a malformed child body draws `ERR_INVALID_REQUEST` even for a nonexistent parent — `implementation/routes/streams.py:77-98, 148-169`
- §2.10 — insert — ambiguity — stage-4 blanket pins: non-JSON-object/absent body → `ERR_INVALID_REQUEST`; integer fields accept integral JSON numbers, booleans never count as numbers; measured/spec numerics accept any JSON number without range checks; free strings (names, emails, permit numbers, state/region codes) checked only for non-emptiness (no two-letter or format validation) — `implementation/common.py:106-172`
- §3.1 — insert — ambiguity — `expected_tons_per_month` must be a positive integer — `implementation/routes/streams.py:34-36`
- §3.2 — insert — ambiguity — determination filing window violation (`valid_until` not after `valid_from`) → `ERR_INVALID_REQUEST` — `implementation/routes/streams.py:156-157`
- §3.2 — revise — mismatch — submission guards fire overlap-check (stage 10) before characterization re-check (stage 12), so a draft failing both draws `ERR_ELIGIBILITY_WINDOW_OVERLAP` (narrative had listed characterization first) — `implementation/routes/streams.py:205-212`
- §3.2 — revise — mismatch — approval runs the overlap guard before the `valid_until` window-past check, in that order (narrative had reversed them) — `implementation/routes/streams.py:242-249`
- §3.2 — revise — mismatch — reinstatement likewise runs overlap before window-past, and leaves `approved_by_user_id` unchanged — `implementation/routes/streams.py:289-304`
- §3.2 — insert — ambiguity — permit `expires_on` before `issued_on` → `ERR_INVALID_REQUEST` — `implementation/routes/permits.py:41-42`
- §3.3 — insert — ambiguity — agreement `committed_monthly_tons` is a positive integer; `counter_month` stamped with the current logical month at creation (not only at activation) — `implementation/routes/agreements.py:32-34, 56`
- §3.3 — insert — ambiguity — commitment `committed_monthly_tons` is a positive integer; `counter_month` stamped at creation — `implementation/routes/agreements.py:163-165, 182`
- §3.6 — insert — ambiguity — redelivery retains the earlier `rejection_reason` (overwritten only by a subsequent rejection) — `implementation/routes/shipments.py:368-385`
- §3.7 — insert — ambiguity — `material_types_allowed` entries must each be one of the five material classes (else `ERR_INVALID_REQUEST`); `capacity_tons` is a strictly positive integer — `implementation/routes/storage.py:15-22, 31-33`
- §3.7 — revise — mismatch — per-day capacity aggregate is evaluated only on days covered by at least one existing `RESERVED`/`CHECKED_IN` reservation; uncovered days are never evaluated, so a reservation overlapping nothing is admitted even if its `tons` alone exceed `capacity_tons` (impl builds per-day sums only over overlapping existing reservations) — `implementation/routes/storage.py:54-71`
- §3.8 — insert — ambiguity — credit-summary `period` defaults to the current logical month when omitted or empty and is not format-validated; an unmatched period yields zeroes — `implementation/routes/misc.py:73`

All other implementation behaviors (endpoint inventory, state machines, freight/settlement/credit formulas and rounding, validation pipeline stage order, error catalog, lazy expiration, cascades, optimistic concurrency) were already uniquely pinned by the PRD and required no change.
