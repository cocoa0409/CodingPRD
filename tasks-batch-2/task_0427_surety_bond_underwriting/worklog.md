# Worklog — task_0427_surety_bond_underwriting

## Step 1: Create Task Directory — 2026-06-20T15:30:21.000Z

Created `tasks/task_0427_surety_bond_underwriting/` and `tasks/task_0427_surety_bond_underwriting/workspace/`. Next index determined by scanning `./tasks/` (max existing = 0426 → 0427).

## Step 2: Generate Scaffold — 2026-06-20T15:50:14.000Z

All three required scaffold artifacts are generated and verified. There's a pre-existing `worklog.md` and empty `workspace/` dir in the directory (not created by me).

### Summary

Generated the three scaffold artifacts for **task_0427_surety_bond_underwriting** purely from the scenario description and the scaffold-generator spec (no sibling tasks consulted). All files pass `scaffold_lint.py` clean, and every numeric/state assertion was replayed in code against the §1.3 formulas.

**Files written** (all under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0427_surety_bond_underwriting/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 + complexity profile
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)

**Complexity profile:** Multi-party-negotiation (underwriting chain) + quota/allocation secondary; flat topology; branching state machines; segregation-of-duties role model; immediate consistency. Advanced band.

**9 Entities:** SuretyProgram, Principal, IndemnityAgreement, BondApplication, Bond, Claim, Rider, ReinsuranceTreaty, Cession.

**6 State machines** (+SuretyProgram/ReinsuranceTreaty status flips): BondApplication (branching fork: SUBMITTED→{APPROVED, REFERRED, DECLINED}, REFERRED→{APPROVED, DECLINED}), Bond (ISSUED→ACTIVE→{CANCELLED, RENEWED, EXPIRED}), Claim (FILED→INVESTIGATING→{PAID, DENIED}), IndemnityAgreement (signature self-loop→EXECUTED), Rider, Cession. One OCC concurrency rule (bond renew, CREATE-with-supersede, `expected_bond_version`, 412).

**7 Calculations:** credit_tier_derivation, premium_rating (tiered table + surcharge + clamp), premium_earning (dual-variant pro-rata/short-rate), incurred_loss (dual-variant case-reserve/paid-actual), rider_premium (pinned round-then-multiply), cession_amount, program_aggregate_exposure.

**15 Validations** (priority-ordered) · **16 Errors** · **3 Roles** (Underwriter, SeniorUnderwriter, ClaimsExaminer — opaque identities, segregation of duties) · **44 endpoints** (incl. `/_clock/set_current_utc` default `2026-01-01T00:00:00Z`).

**Design counts:** §1.8 = 18 difficulty instances (all 9 rules × 2, each with distinct entity domains / category pairs / interval semantics / conserved quantities). §1.9 = 34 corner instances (29 active recipes + 5 `excluded_because` stubs pointing at real §1.8 instances) across all nine claim-extraction-guide sections. Lint: 375 calls scanned, clean; all grounds resolve; enum closure satisfied; no forbidden concurrency vocabulary; all instance names unique.

One scenario-driven note: introduced a dedicated `loss_alert_threshold_cents` on SuretyProgram (distinct from `aggregate_limit_cents`) so the "claim settle → program auto-suspend" depth-3 cascade is actually reachable (paid loss is bounded by penal ≤ aggregate capacity, so it could never breach the exposure limit itself).

## Step 3: Copy Shared Files — 2026-06-20T15:50:39.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0427_surety_bond_underwriting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-20T15:55:55.000Z

All rule-coverage spot-checks pass. The PRD is complete and all three Hard Contracts are satisfied. (`workspace/PRD.md`, 249 lines / ~5,950 words.)

### Summary

Generated `workspace/PRD.md` for the Surety Bond Underwriting domain.

#### Structure
- **§1 Introduction** — 2 paragraphs framing the domain as finite-capacity accounting with segregation of duties.
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Properties & Concurrency, 2.5 OCC on Renewal, 2.6 Program Exposure Accounting, 2.7 Loss Accumulation & Loss-Alert Brake, 2.8 Treaty Capacity & Cession Accounting, 2.9 Monetary Precision, 2.10 The Logical Clock, 2.11 Reference Resolution Order, 2.12 Request Validation Ordering.
- **§3 Business Logic** — 7 subsections grouped by lifecycle: Establishing Capacity (programs/treaties), Principals/Credit/Indemnity, Application/Quote/Underwriting Fork, Binding & Issuing, Servicing (riders/cessions/renewal/cancel/expiry), Filing & Investigating Claims, Settling Claims & Loss Cascade.
- **§4** 4-column endpoint table (44 endpoints incl. the clock).
- **§5** 2-column error catalogue (15 errors).

#### Hard Contracts — all PASS
- **Contract 1 (Field-Name Coverage):** 54 required identifiers (47 entity fields + 7 endpoint inputs/params), 54 present, 0 missing. Caught and fixed two FK input names (`bond_id`, `treaty_id`) initially rendered as "the bond's/treaty's identifier."
- **Contract 2 (Rule Coverage):** all state transitions with from/to + preconditions paired to error IDs; all 7 calculations expressed in precise prose; 15-rule validation priority order stated explicitly in §2.12; OCC rule expressed in stale-version terms with `expected_bond_version` + `ERR_STALE_VERSION` + 412; all cross-entity cascades stated.
- **Contract 3 (§3 Path Purity):** 316 backtick tokens scanned in §3; 0 slash-paths, 0 bare HTTP methods, 0 method+path combos.

#### Notable coverage decisions
- All three roles are `identity: opaque`; §2.1 states `X-User-ID` is an opaque operator identifier never compared to any entity `id`.
- The two dual-variant calculations (premium earning pro-rata vs short-rate; incurred loss case-reserve vs paid-actual) given equal density; the two distinct pinned-rounding orders (cancel = sum-then-round; rider = round-then-multiply) stated explicitly.
- Logical clock default (`2026-01-01T00:00:00Z`, no wall-clock fallback) and its role in elapsed-month math documented.
- Withheld design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-06-20T16:10:04.000Z

All asserted literals are arithmetically correct and match the design-yaml's pre-computed values. The test suite is complete and verified.

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 10 status/role enums + 9 entity TypedDicts (all carry `id/created_at/updated_at/version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 9 entities + clock)
- `api_errors.py` — 15 `ApiErrorId` values + HTTP-status map, registered with framework
- `assertions.py` — per-entity assertions with derived-field invariants (`net_retained`, `aggregate_available`, `ceded_available`)
- `factories.py` / `constants.py` / `test_users.py` (all 3 roles opaque) / `fixtures.py` (tiered composite helpers for the program→principal→GIA→app→bond→issue funnel, plus claims/cessions/riders) / `__init__.py` barrel export

### Stage 2 — `test_suite/` (6 files, 64 tests)
| File | Tests |
|---|---|
| `conftest.py` | fixture bridge |
| `test_01_premium_and_loss_calculations.py` | 10 |
| `test_02_state_machines_and_workflows.py` | 10 |
| `test_03_cascades_and_invariants.py` | 13 |
| `test_04_limits_and_boundaries.py` | 18 |
| `test_05_crud_rbac_and_concurrency.py` | 13 |

### Design-instance translation
- **Difficulty queue (A):** 18 instances total → **17 translated** (each with ≥2 tests), **1 skipped**.
  - Skipped: `priority_pair_validation_conflict/safety_vs_fiscal_on_rider_apply` — fails unique-derivability under the `validation-priority` silence pattern. It asserts `ERR_OPEN_CLAIM_EXISTS` wins over `ERR_SINGLE_LIMIT_EXCEEDED` when both fail, but both are *operation-specific business rules*; the PRD commits to no strict precedence *between two business rules*, so a faithful PRD-only implementer could check single-limit first. Sibling `state_vs_referential_on_submit` kept (its recipe only ever lets the priority-5 state gate fire).
- **Corner queue (B):** 34 instances total → 5 `excluded_because` stubs correctly not translated (all 5 cross-references resolve to real difficulty instances), **all 29 non-stub instances translated** (≥1 test each).

### Verification performed
- All 15 helper + test files compile; every test docstring ends with exactly one verbatim `Design:` tag; no untagged/dual-tagged tests; no `skip`/`skipif`/`xfail`.
- All PRD citations confirmed verbatim-present; AST check (imports resolve, `api.<method>` calls exist); all asserted numeric literals independently recomputed and matched.

## Step 6: Generate Implementation — 2026-06-20T16:10:04.000Z

All 44 endpoints implemented (matching the 44 routes in the PRD/scaffold endpoint table), all smoke tests pass, server boots cleanly via `start.sh`.

### Files (23 total)
- `start.sh` — guarded-install foreground launcher (`exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` — `flask>=2.0`
- `app.py` — blueprint wiring + standard error-envelope handlers (no seeding at startup)
- `db.py` — in-memory dict store (9 entity maps) with a monotonic `_seq` for stable sort tie-break; resets fully on each boot
- `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `clock.py`, `serializers.py`
- `services/calculations.py` (rating/premium/cession math), `services/domain.py` (exposure + loss recompute, `touch()` for version/timestamp bumps)
- `routes/` — 10 blueprints: clock, programs, principals, indemnity_agreements, applications, bonds, claims, riders, treaties, cessions

### Endpoint count: 44 (exact match to PRD §4 / scaffold §1.5)

### Notable implementation decisions
- Response envelope / auth / errors read verbatim: `meta`/`response_type`/`data`; headers `X-User-Role` (+ opaque `X-User-ID`); pagination `limit`(10/1/100)/`offset`(0)/`total_count`/`has_more`; all 15 error IDs with exact HTTP statuses (`ERR_INVALID_REQUEST`=422, `ERR_STALE_VERSION`=412, 409 family).
- Validation precedence (PRD §2.12): auth(401) → RBAC(403) → existence L-to-R(404) → body well-formedness(422) → state(409) → OCC(412) → business rules.
- Money math: `Decimal` + ROUND_HALF_UP with PRD's pinned rounding orders (premium rating 2-step select-then-round, 50bps large-risk surcharge, 400bps clamp; short-rate cancel sum-then-round; rider INCREASE round-per-month-then-multiply). Verified against worked examples (pro-rata 3750, short-rate 4875, rider 5625).
- Logical clock defaults `2026-01-01T00:00:00Z`, never wall-clock; drives `months_between` (complete-calendar-month) for earned/rider premium; stamps `created_at`.
- Cross-aggregate cascades centralized in `services/domain.py`: program `aggregate_committed_cents` and treaty `ceded_committed_cents` maintained incrementally; cancel/expire release net-retained before recapture; renewal shifts exposure predecessor→successor; claim-PAY recomputes program cumulative loss and auto-SUSPENDs on loss-alert brake; every mutated resource gets `version` bump + `updated_at`.
- Segregation of duties: front-line Underwriter approving a REFERRED application → 403 (senior-only); ClaimsExaminer walled off from bind/approve; clock + program/treaty config senior-exclusive.
- **NOTABLE AMBIGUITY flagged by impl-gen**: Renew returns the *predecessor* bond (the resource at `{id}`, now RENEWED with `superseded_by_bond_id` set); successor reachable via bonds list filters. "If tests expect the successor object this is the place to flip." — watch this in Step 7.
- All state in-memory only; nothing persisted; nothing seeded. 72 smoke-test assertions across four scenarios pass; `start.sh` reaches HTTP-ready in ~1s.

## Step 7: Run Tests and Iterate — 2026-06-20T16:14:20.000Z

All 8 parallel rounds passed cleanly on the first sweep. Exiting per the contract (all 8 rounds have `passed == total`). Verified independently: results.{1..8}.json all report passed=64 total=64 failed=0 errors=0.

### Summary

**Iterations run:** 1 (the initial 8-round parallel stability sweep)

**Result:** All 8 concurrent rounds passed 64/64 tests (failed=0, errors=0, skipped=0 in every round). No flakiness surfaced — the union of failing tests across all 8 rounds is empty.

**Tests deleted:** None. Every test traced to a verbatim PRD sentence and the assertions were uniquely derivable from PRD prose.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None.

**Diagnostic notes (no action required):**
- Read full PRD, all 5 test suites (64 tests), all test_helpers, and the entire Flask implementation before running.
- Correctness points exercised and honored: validation priority order (auth → RBAC → existence → body-shape → state → OCC → business rules), round-then-multiply rider premium vs sum-then-round short-rate earned premium, the loss-alert suspend cascade on PAY settle, cession/recapture exposure conservation, OCC on renew via `expected_bond_version` (412), inclusive referral threshold (`>=` triggers `ERR_REFERRAL_REQUIRED`).
- Storage is in-memory only (`db.py` `Store` dicts, no startup seeding); `start.sh` binds `0.0.0.0:$PORT`, uses `exec`, installs Flask only when missing.

## Step 8: Finalize PRD — SKIPPED — 2026-06-20T16:14:20.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. `PRD_FINALIZED.md` not produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-20T16:19:03.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD.md` (Step 8 skipped, no PRD_FINALIZED.md). All 7 edits in-paragraph; no new lines/sections.

### Summary

**Line counts:** PRD.md = 249 lines / 41,711 chars; PRD_COMPLETED.md = 249 lines / 43,010 chars (char delta **+1,299**).

**Counts:** ambiguity-pins = **6**, mismatch-revisions = **1**.

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (not rejected); non-integer values yield `ERR_INVALID_REQUEST` — `helpers.py:99-114`.
- §2.10 The Logical Clock — insert — ambiguity — `set_current_utc` validates `to_iso8601` (else `ERR_INVALID_REQUEST`), returns HTTP 200 with empty-object `data` — `routes/clock_route.py:17-25`.
- §3.3 Application/Quote — insert — ambiguity — `quoted_premium_rate_bps`/`quoted_premium_cents` both null until submit — `routes/applications.py:54-55`.
- §3.3 Underwriting fork — insert — ambiguity — front-line `Underwriter` approving a `REFERRED` application gets `ERR_FORBIDDEN` (application unchanged) — `routes/applications.py:138-139`.
- §3.4 Issuing — insert — ambiguity — `power_of_attorney_number` format (`POA-` + 12 uppercase hex chars) — `routes/bonds.py:139`.
- §3.5 Renewal — insert — ambiguity — renew response (200) returns the predecessor bond in `RENEWED` with `superseded_by_bond_id` set, not the successor — `routes/bonds.py:264-269`. (Resolves the ambiguity impl-gen flagged in Step 6.)
- §3.6 Filing Claims — revise — mismatch — corrected "these are unset at filing": impl sets `paid_loss_cents` to null but `salvage_cents` to 0 (not null) at filing — `routes/claims.py:51-52`.

**Verified already-pinned (no change):** RBAC roles/read scopes, rate table, credit-tier derivation, large-risk surcharge boundary, rate clamp at 400, all rounding orders, elapsed-months/clamping, exposure & loss accounting cascades, treaty/cession math, validation ordering (§2.12), reference-resolution order (§2.11), OCC on renew, terminal-state sets, default values, serializer field shapes. §3.7 loss-brake "drive to SUSPENDED" left unpinned as the PRD language already accommodates the no-op-when-already-SUSPENDED degenerate case.

---

## Pipeline Complete — 2026-06-20T16:19:03.000Z

All 9 steps done. Final test status: **64/64 passing across all 8 parallel rounds** (failed=0, errors=0). Task `task_0427_surety_bond_underwriting` is ready.
