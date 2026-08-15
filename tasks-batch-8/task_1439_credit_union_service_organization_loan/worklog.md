# Worklog — task_1439_credit_union_service_organization_loan

## Step 1: Create Task Directory — 2026-08-13T07:14:00.000Z

Task directory `tasks/task_1439_credit_union_service_organization_loan/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command; treated as DONE (no index scan, no other task dir touched).

## Step 2: Generate Scaffold — 2026-08-13T08:11:00.000Z

All three artifacts are written and verified. Lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design`

## Scaffold counts (§1.0–§1.7)

- **Entities: 13** — CreditUnion, CUSO, CUSOInvestment, ServicingAgreement, ParticipationOffering, ParticipationCertificate, DocumentationException, Remittance, SurveillanceReport, RegulatoryExam, ExamFinding, LossEvent, RepurchaseCase (flat topology, all FK-linked, every FK has a reverse-reachability GET)
- **State machines: 13** — three cyclic (DocumentationException cure/reject/resubmit, ExamFinding reopen loop, ServicingAgreement ACTIVE↔DELINQUENT), plus auto-transitions (PAID_OFF, offering auto-close, sweep-driven expiry/escalation) and system cascades
- **Calculations: 7** — accrued_interest (30/360 vs ACT/360 variants), remittance_settlement (pinned evaluation order + late penalty), investment_cap_check (tiered base/extended caps), concentration_share, loss_share_allocation (OUTSTANDING vs COMMITTED variants + pinned round-per-share-then-residual order, `created_at` tie-break), repurchase_price, surveillance_pool_aggregates (WAC weighting variants)
- **Validations: 12** ordered priorities (auth → ownership → existence → request shape → OCC 412 → state → safety → referential → temporal → constraint → fiscal)
- **Endpoints: 63** including `POST /network/sweeps/run` (ops-run checkpoint) and `POST /network/_clock/set_current_utc` (default `2026-08-01T00:00:00Z` stated in description)
- **Errors: 28**; **Roles: 6** (NetworkAdmin/RegulatorUser opaque; TreasuryUser/OriginatorUser/BuyerUser entity_backed:CreditUnion; CUSOOfficer entity_backed:CUSO; segregation-of-duties on finding verify vs recorder)
- **Concurrency: 1** OCC rule (`surveillance-report-stale-agreement`, ERR_STALE_VERSION 412 on ServicingAgreement.version)

## Design instances

- **Difficulty (§1.8): 19 instances** across all 9 rules, each ≥2 — combinatorial_formula has 3 (modes a, b, c). All fixture math pre-computed as literals (e.g., interest 50,000 vs 51,667; fee 2,083 vs 2,153; WAC 640 vs 633; loss residual [34,33,33]; penalty 3,030; cap equality 50,000,000 == cap allowed / +1 rejected; cure at exact deadline allowed / +1s rejected).
- **Corner (§1.9): 37 active instances + 11 excluded_because stubs** across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting / consistency_model. Name uniqueness across both files and stub→§1.8 references mechanically verified; no forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-08-13T08:13:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1439_credit_union_service_organization_loan/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T08:30:00.000Z

PRD generated and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/workspace/PRD.md` — 304 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (headers, 6 roles, per-role `identity:` prose, ownership mapping), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending), 2.4 Logical Clock (startup default 2026-08-01T00:00:00Z, `to_iso8601` → `current_utc`), 2.5 Monetary Precision & Day-Count (whole cents half-up; caps round down; 360-day year; `THIRTY_360` vs `ACT_360` with the August example), 2.6 Common Properties & OCC (`id`/`created_at`/`updated_at`/`version`; `expected_servicing_agreement_version` → `ERR_STALE_VERSION` 412), 2.7 Validation Order (all 12 priorities explicitly ordered), 2.8 Cascading State Propagation, 2.9 Regulatory Thresholds (1%/3% caps, 7% well-capitalized, 0.25 concentration default, 3 bps/day penalty, defaults 0/30/2)
- §3 Business Logic (10 subsections): onboarding; CUSO investment review + cap check; servicing agreements; offerings + commitments; remittance lifecycle + delinquency cascade + reversal; documentation exceptions + cures + repurchase; loss events + allocation; surveillance reporting + supersession; exams/findings + enforcement cascade; ops-run sweep (3 families, atomic)
- §4 Endpoint Definitions: all 63 endpoints, 4-column table
- §5 Error Code Catalogue: all 28 errors, 2-column table

**Coverage audit:**
- **Contract 1 (fields):** every entity field plus every endpoint request/query/output identifier (`accept`, `verification_passed`, `to_iso8601`, `current_utc`, `remittances_marked_late`, `exceptions_escalated`, `offerings_expired`, `expected_servicing_agreement_version`, `limit`, `offset`, …) present in backticks — mechanically verified, 0 missing. All 6 roles, 28 error IDs, and every enum/state value present.
- **Contract 2 (rules):** 12/12 validation priorities in ordered prose; 1/1 OCC rule fully expressed (write capability + OCC field + `ERR_STALE_VERSION`/412, no race framing); all transitions across the 13 state machines expressed with preconditions, error IDs, and cascades (including the dual-precondition `EXCEPTION→ACTIVE`, repurchase-complete from both `ACTIVE` and `EXCEPTION`, `PAID_OFF→ACTIVE` on reversal, close-on-DRAFT → `WITHDRAWN` vs close-on-`OPEN` → `CLOSED`); 7/7 calculations as precise reconstructible prose (pinned settlement order, per-share-then-residual loss rounding with fractional-part DESC / `created_at` ASC tie-break, cap boundary inclusivity, concentration exclusion set, repurchase accrual window, WAC variants with empty-pool zero); all applies_to scopes and endpoint side-effects covered; defaults and system-stamped fields reconstructible.
- **Contract 3 (§3 path purity):** 521 backticked tokens scanned, 0 violations (no paths, no bare HTTP methods).

## Step 5: Generate Unit Tests — 2026-08-13T09:05:00.000Z

All 77 tests collect cleanly. Generation complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/`):

`test_helpers/` (9 files): `__init__.py` (barrel export, 127 names), `types.py` (13 entity TypedDicts + 13 status/role enums), `api_client.py` (`ApiClient(GenericApiClient)` with all 48 endpoints), `api_errors.py` (27 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions), `factories.py` (13 payload factories), `constants.py` (cap/penalty/day-count thresholds, clock default), `test_users.py` (shared constants + per-instance builders for the four entity-backed roles), `fixtures.py` (composite setups: `setup_pool`, `setup_pool_with_funded_cert`, `setup_day_count_pair`, `setup_wac_pool`, `setup_loss_rounding_pool`, `setup_delinquent_agreement`, `setup_investor`, `suspend_cuso_with_open_critical`, etc., all with entity-backed identity threading).

`test_suite/` (11 files): `conftest.py` + `test_01_onboarding_access.py` (7), `test_02_investment_review.py` (9), `test_03_commitment_gatekeeping.py` (12), `test_04_offering_state_and_aggregates.py` (11), `test_05_remittance_settlement.py` (12), `test_06_sweeps_and_delinquency.py` (5), `test_07_exceptions_and_repurchases.py` (7), `test_08_loss_allocation.py` (3), `test_09_surveillance.py` (3), `test_10_exams_and_supervision.py` (8).

**Test counts**: 77 total — Queue A (Difficulty): 41 tests covering all 19 instances at ≥2 each (most 2; `investment_cap_tiered_branching` 4; `referential_beats_temporal_on_commitment` 3). Queue B (Corner): 36 tests, one per translated non-stub instance.

**Skipped instances (1)**:
- `Corner/validations/allocate_with_no_eligible_certificates_rejected` — fails unique derivability: with zero `{ACTIVE, EXCEPTION}` certificates the total basis weight is 0, so any positive loss simultaneously violates the `ERR_LOSS_EXCEEDS_POOL` rule; both sit in the same §2.7 priority-12 group, and §2.7 lists `ERR_LOSS_EXCEEDS_POOL` before `ERR_NO_ALLOCATABLE_CERTIFICATES` while §3.7 prose describes the eligibility check first — two PRD-faithful implementers could return either error. No isolated single-failure scenario exists (loss_amount must be positive). Skipped per the validation-priority silence pattern; no placeholder emitted.

**Corner stubs (11)**: not translated; all `difficulty_instance` cross-references verified to resolve to real §1.8 instance names.

**Coverage reconciliation**: every one of the 19 difficulty instances has ≥2 tests; 36/37 non-stub corner instances have exactly 1 test; the 1 remaining instance has the explicit skip reason above. Machine-verified: zero untagged tests, zero dual-tagged tests, zero tags pointing to non-existent instances, zero stub tags.

**Additional verification**: all 121 quoted PRD citation sentences grep verbatim in `workspace/PRD.md` (whitespace-normalized); all files compile; `test_helpers` imports cleanly against the installed framework; pytest collects 77 tests. No `skip`/`skipif`/`xfail` markers; no scaffold references in comments/docstrings.

**Two deliberate PRD-faithfulness adjustments**: (a) `setup_loss_rounding_pool` advances the logical clock between the three commitments so `created_at` values are distinct and ascending, making the §3.7 residual tie-break (`created_at` ascending) deterministic — the clock is otherwise frozen at startup default; it also uses pool 90,000 / min_share 0.001 instead of the recipe's 900 so remaining principal never hits zero pre-funding, sidestepping the ambiguous auto-close-on-fund trigger (asserted literals [34,33,33] and per-cert balances unchanged); (b) computed-timestamp equality (`due_at`, `cure_deadline`, `paid_at`) is asserted via value-prefix comparison since §2.6 pins millisecond formatting only for `created_at`/`updated_at`, leaving other timestamps' rendering open to faithful variants.

## Step 6: Generate Implementation — 2026-08-13T09:12:00.000Z

Implementation complete and verified. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/workspace/implementation/`):
- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask is present, so per-test reboots don't contend), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (Flask entry, blueprint registration, envelope-aware 404/405/500 handlers)
- `db.py` — in-memory dict stores (13 entity kinds, all empty at boot; zero seeding) plus the logical clock
- `errors.py` — full 27-id error catalog with HTTP statuses
- `response.py` — envelope: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, pagination fields in `meta` for lists
- `middleware.py` — X-User-ID/X-User-Role auth (six declared roles), role gate, body/enum/int/datetime validators, `limit`/`offset` pagination (default 10, 1..100), per-request `touch()` (version bump + `updated_at` refresh, idempotent per entity per request)
- `serialize.py` — per-entity serializers; cross-entity aggregates (committed principal, CUSO approved totals, open-critical counts) computed at read time
- `services/calc.py` — all money math in `Decimal`: day-count variants (THIRTY_360 full-month-30/partial-min(actual,30), ACT_360 inclusive), accrued interest/fee (round-half-up, 360-day year), late penalty (3 bps/day on interest+principal), caps rounded DOWN (base 1%, extended 3%, well-capitalized 0.07 ratio), concentration cap, loss allocation (per-share round-half-up, then 1-cent residual by fractional part DESC / created_at ASC, then cap-at-outstanding with iterative pro-rata redistribution), WAC
- `services/cascade.py` — supervisory cascade (CUSO↔agreements↔offerings), delinquency cascade via stored `late_remittance_count`, certificate EXCEPTION→ACTIVE reactivation gate, aggregate-recompute touches
- `routes/` — 12 modules: credit_unions (also CUSOs), investments, agreements, offerings, commitments, exceptions, remittances, surveillance, exams (also findings), loss_events, repurchase_cases, ops (sweep + `_clock/set_current_utc`)

**Endpoint count: 63** (all from the scaffold endpoint table, including `POST /network/sweeps/run` and `POST /network/_clock/set_current_utc`).

**Notable design decisions:**
- **Clock**: module-level logical clock defaulting to exactly `2026-08-01T00:00:00Z`; every timestamp (entity `created_at`/`updated_at`/`decided_at`/`paid_at`, deadlines, and the meta `api_request_timestamp`) reads it — never wall-clock. Serialized as ISO 8601 UTC with three fractional digits.
- **Validation ordering** follows PRD §2.7 strictly: auth → role → ownership → existence → shape → OCC (412 on `expected_servicing_agreement_version`) → state → caps/SoD → linked-entity state → windows → domain → funds. Caller-bound body fields (`credit_union_id`, `cuso_id`) are ownership-checked before existence (pure string compare, per priority 3 before 4).
- **Cascades**: CUSO suspend/reinstate drags ACTIVE/SUSPENDED agreements and their OPEN/SUSPENDED offerings; delinquency flip occurs only at increment time when the agreement is ACTIVE and count ≥ threshold; reinstatement only when count returns to 0 from DELINQUENT. Each cascaded resource gets its own version bump.
- **Auto-close nuance**: offering closes at fund time only when `remaining_principal_cents == 0` AND no PENDING_DILIGENCE/COMMITTED certificates remain (per the scaffold's clarifying note), so multi-buyer pools stay open until the last commitment funds.
- **OCC**: surveillance publish requires the version field (400 if missing), supersedes the prior CURRENT report (bumped), and increments the agreement version by exactly 1.
- **Repurchase price**: outstanding + accrued from day after the most recent remittance `period_end` (any status) or funded date, through completion date inclusive, under the agreement's day-count.

Verified with two throwaway smoke suites (auth/envelope, caps incl. ENHANCED eligibility, both day-count variants, penalty math, sweep late-flip with grace edge and delinquency cascade, cure loop incl. deadline expiry and escalation auto-cases, loss allocation exact/residual splits, WAC both bases, OCC 412, exam cascade and reinstate, error-priority orderings, pagination) — all pass against fresh server boots via `start.sh`.

## Step 7: Run Tests and Iterate — 2026-08-13T09:25:00.000Z

All 8 rounds pass 77/77. Clean sweep achieved.

## Summary

- **Iterations run**: 2 (initial 8-round sweep → diagnose/fix → final 8-round sweep, all 8 rounds at 77/77).

- **Tests deleted**: None.

- **Fixes applied to `test_helpers/`**: None.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/test_suite/test_04_offering_state_and_aggregates.py` — added missing `setup_pool_with_funded_cert` to the `from test_helpers import (...)` block; `TestCertificateTerminalLockdown::test_approve_diligence_on_active_certificate_rejected` referenced it without import (NameError).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/test_suite/test_07_exceptions_and_repurchases.py` — `TestRepurchasePriceAndUniqueness::test_repurchase_price_stamped_on_complete` asserted `offering_after["committed_principal_cents"] == 90_000_000`. PRD §3.4 defines `committed_principal_cents` as the sum of `committed_amount_cents` over `PENDING_DILIGENCE`/`COMMITTED`/`ACTIVE`/`EXCEPTION` certificates; after the only certificate (10M of a 100M pool) moves to `REPURCHASED`, the sum must be 0 (the buyer's `total_committed_principal_cents` assertion of 0 already encoded this). The 90M figure was the pre-repurchase `remaining_principal_cents`, not the post-repurchase `committed_principal_cents`. Changed to 0.

- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/workspace/implementation/routes/exceptions.py` — `create_exception` previously gated flagging to `cert["status"] == "ACTIVE"`. PRD §3.6 states "When an exception is cured and **no other exception of the certificate** remains in `OPEN`, `CURE_SUBMITTED`, `REJECTED`, or `ESCALATED`..." — the "no OTHER exception" clause presumes multiple concurrent exceptions per certificate, which is only reachable if flagging is also allowed from `EXCEPTION`. Widened the gate to `("ACTIVE", "EXCEPTION")`.

## Step 8: Finalize PRD — 2026-08-13T09:30:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one in-place revision.

**Line counts / delta**
- `PRD.md`: 303 lines; `PRD_FINALIZED.md`: 303 lines (single in-place sentence revision, 0% line-count delta; one paragraph rewritten on line 166).

**Changes**
- §3.6 — revise — replaced "Creating the exception also cascades the certificate from `ACTIVE` to `EXCEPTION`." with wording pinning that flagging is permitted while the certificate is `ACTIVE` **or** `EXCEPTION` (other states → `ERR_INVALID_STATE`), that an `ACTIVE` certificate moves to `EXCEPTION` while an `EXCEPTION` certificate remains `EXCEPTION`, so multiple concurrent exceptions per certificate are possible — `implementation/routes/exceptions.py:52-53,66`.

**Step_7_diff items disposition**
- Test import fix (`test_04...py`): pure fixture bug — no PRD edit.
- Test repurchase `committed_principal_cents` 90M→0 (`test_07...py`): PRD §3.4 already defines `committed_principal_cents` over `PENDING_DILIGENCE`/`COMMITTED`/`ACTIVE`/`EXCEPTION` only, and §3.6 already states the recomputed aggregates "thereafter exclude the repurchased position"; impl `serialize.py:5,50-55` (`OPEN_CERT_STATUSES`) matches exactly. Verified — no PRD silence, no edit.
- `create_exception` gate widened to `("ACTIVE", "EXCEPTION")`: PRD §3.6 previously implied ACTIVE-only — patched as above.

**Per-edit pre-edit search log**
- Edit 1 (§3.6 flagging gate):
  - (a) Subject: which certificate statuses permit flagging a documentation exception, and the resulting certificate status.
  - (b) Enumerated impl paths read/grepped: `implementation/routes/exceptions.py` (full file — create gate at lines 52-53, status set at 66; submit-cure/verify-cure operate on exception status only); `implementation/services/cascade.py:94-109` (`certificate_maybe_reactivate` — EXCEPTION→ACTIVE when no exceptions in OPEN/CURE_SUBMITTED/REJECTED/ESCALATED and no cases TRIGGERED/DISPUTED); `implementation/routes/repurchase_cases.py:55,122` (repurchase create/complete gates ACTIVE-or-EXCEPTION, already pinned in PRD §3.6); `implementation/routes/loss_events.py:18` and `routes/surveillance.py:19` (eligibility pools {ACTIVE, EXCEPTION}, already pinned in §3.7/§3.8); `implementation/routes/remittances.py:69,135` (schedule/pay require ACTIVE only — unaffected); `implementation/routes/ops.py:53-64` (sweep escalation, unaffected); `implementation/serialize.py:5` (`OPEN_CERT_STATUSES`); plus grep for all `EXCEPTION` occurrences across `implementation/`.
  - (c) Wording adjustment: scoped the new sentence strictly to the flagging operation ("Flagging is permitted while the certificate is in `ACTIVE` or `EXCEPTION`") rather than a broad claim about the `EXCEPTION` state, so it does not imply remittance scheduling/payment or other ACTIVE-only operations accept `EXCEPTION`; phrased the cascade as "moves an `ACTIVE` certificate to `EXCEPTION`, while a certificate already in `EXCEPTION` remains `EXCEPTION`" — a status-only claim that stays silent on the `touch`/version bump (which §2.8's generic mutation rule already covers), avoiding any false universal about no-op transitions.

## Step 9: Complete PRD — 2026-08-13T09:58:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1439_credit_union_service_organization_loan/workspace/PRD_COMPLETED.md` (306 lines / 54,827 chars vs. source `PRD_FINALIZED.md` 303 lines / 52,859 chars; **+3 lines, +1,968 chars**). All changes are inline inserts/revisions; no new sections.

**Counts: 16 ambiguity-pins, 1 mismatch-revision (17 total edits).**

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.2 Error Response Format — insert — ambiguity — pinned that unmatched routes/methods return the error envelope with `ERR_NOT_FOUND` (404) and unexpected failures with `ERR_INTERNAL` (500) — app.py:38-52
- §2.3 Pagination — insert — ambiguity — pinned `ERR_INVALID_REQUEST` for non-integer limit/offset, out-of-range limit, negative offset; pinned `created_at` ties broken by insertion order — middleware.py:173-213
- §2.4 Logical Clock — insert — ambiguity — pinned the supplied `to_iso8601` is applied verbatim (no monotonicity requirement) — routes/ops.py:18-25
- §2.6 Common Resource Properties — insert — ambiguity — pinned `version` starts at 1 on creation — db.py:87-93
- §2.8 Cascading State Propagation — insert — ambiguity — pinned at-most-once-per-request versioning per resource (touch dedup) — middleware.py:220-230
- §2.7 Validation Order item 12 — revise — mismatch — reordered so `ERR_NO_ALLOCATABLE_CERTIFICATES` precedes `ERR_LOSS_EXCEEDS_POOL`, matching the actual check order — routes/loss_events.py:97-105
- §3.1 CU registration — revise — ambiguity — pinned `total_assets_cents`/`net_worth_cents` as positive integers, `concentration_cap_pct` positive when supplied, duplicate `charter_number` → `ERR_INVALID_REQUEST` — routes/credit_unions.py:27-35
- §3.2 Investment submission — insert — ambiguity — pinned `ERR_NOT_RESOURCE_OWNER` when `credit_union_id` ≠ `X-User-ID` — routes/investments.py:29-31
- §3.3 Agreement creation — revise — ambiguity — pinned `ERR_NOT_RESOURCE_OWNER` on `cuso_id` mismatch; pinned `servicing_fee_bps`/`grace_period_days`/`cure_period_days` as non-negative integers and `late_remittance_threshold` as a positive integer — routes/agreements.py:36-57
- §3.4 Offering fields — revise — ambiguity — pinned `min_share_pct` positive number, `yield_rate_bps` non-negative integer — routes/offerings.py:51-54
- §3.4 Commitment creation — insert — ambiguity — pinned `committed_amount_cents` as a positive integer — routes/commitments.py:55
- §3.4 Commitment battery — insert — ambiguity — pinned the agreement-must-be-`ACTIVE` check (`ERR_AGREEMENT_NOT_ACTIVE`) evaluated before the offering-open check — routes/commitments.py:70-74
- §3.4 Auto-close on funding — revise — ambiguity — pinned impl's actual trigger: close only when remaining is zero AND no certificate remains in `PENDING_DILIGENCE`/`COMMITTED` (the old sentence's literal trigger never fires, since funding doesn't change `remaining_principal_cents`) — routes/commitments.py:197-210
- §3.7 Loss reporting — insert — ambiguity — pinned originator ownership (`ERR_NOT_RESOURCE_OWNER`) on both report and allocate — routes/loss_events.py:28-32,44-45,88-89
- §3.7 Allocations shape — revise — ambiguity — pinned entries as `{"certificate_id", "allocated_cents"}` ordered by certificate `created_at` ascending — services/calc.py:174-176, routes/loss_events.py:92-96
- §3.8 Surveillance — insert — ambiguity — pinned that a non-empty pool whose weights sum to zero also reports `weighted_avg_yield_bps` 0 — routes/surveillance.py:69-79
- §5 Error Catalogue — insert — ambiguity — added `ERR_INTERNAL | 500` row (companion to the §2.2 pin) — app.py:48-52

Everything else in the implementation — all 51 endpoints and their filters, every state machine transition, the cap math (base/extended caps, enhanced-basis eligibility order), concentration check ordering, the pinned settlement split, late-penalty formula, day-count conventions (including 30-day full-February behavior under `THIRTY_360`), loss residual/cap redistribution, repurchase price accrual (anchored on the most recent `period_end` including `REVERSED` remittances, per PRD's unqualified wording), the three sweep families, and all serializer field shapes — was already uniquely pinned by PRD_FINALIZED.md and required no change.
