# Worklog — task_0011_applicant_tracking_system

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Created `./tasks/task_0011_applicant_tracking_system/workspace/` using pre-allocated path (ID 0011 reserved to avoid collision with task_0009, task_0010, task_0012 concurrent pipelines).

## Step 2: Generate scaffold — 2026-05-27T02:43:00Z

Three files produced: `SCAFFOLD.yaml` (65 KB, §1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (80 KB, §1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (84 KB, §1.9).

Orchestrator post-fix: bare-word `?`-suffixed tokens in `input:` flow sequences (e.g. `[limit?, offset?, ...]`) were quoted to make SCAFFOLD.yaml parse as YAML. Semantics-preserving (those entries were always intended as strings).

Generation summary (verbatim from subagent):

### §1.8 instance counts per rule (2 each → 18 total)
- `dual_variant_calc`: 2 (referral_bonus estimated_vs_payable, diversity_pool_vs_hire)
- `combinatorial_formula`: 2 (mode (a) three-factor conditional, mode (b) nested rounding order)
- `non_linear_state_machine`: 2 (Offer branching, BackgroundCheck branching with divergent cascades)
- `transitive_cascade`: 2 (offer-accept depth-3, requisition-cancel depth-3)
- `priority_pair_validation_conflict`: 2 (SoD vs budget, panelist_conflict vs invalid_panel)
- `boundary_precision_check`: 2 (interview score exactly 4.50, offer accept exactly at expires_at)
- `cross_entity_state_dependency`: 2 (Application→Requisition, Offer→Requisition with different verbs)
- `resource_temporal_overlap`: 2 (per-application half-open, per-panelist 15-min buffered)
- `compensating_invariant`: 2 (Department.committed_offer_cents round-trip, JobRequisition.filled_count round-trip via BGC FAILED)

### §1.9 instance counts per section (38 total = 29 active + 9 excluded_because stubs)
- `entities`: 6 active (creation, defaults, NOT_FOUND, FK_NOT_FOUND, computed field, immutability)
- `state_machines`: 4 active (invalid-from-DRAFT, terminal lockdown on HIRED, first-interview cascade, other-app cascade on HIRE)
- `calculations`: 3 active (2dp rounding, 90-day decay cutoff, zero-denominator diversity)
- `validations`: 6 active + 8 excluded (active: DUPLICATE_APPLICATION/OFFER, PANELIST_NOT_ASSIGNED, FEEDBACK_INCOMPLETE, SALARY_OUT_OF_BAND, BGC_INDEPENDENCE; excluded: SoD/BUDGET/PANELIST_CONFLICT/INVALID_PANEL/OFFER_EXPIRED/INVALID_STATE/two OVERLAPs already covered in §1.8)
- `endpoints`: 2 active (list+pagination envelope, clock-endpoint revoked_offer_ids)
- `rbac`: 4 active (Recruiter cannot approve req, Candidate cannot create req, Payroll cannot resolve BGC, missing-auth 401)
- `cross_cutting_complexity_layers`: 3 active + 1 excluded (OCC stale on VP approve, OCC stale on cancel, revoke cascade; dual_variant excluded as §1.8-covered)
- `consistency_model`: 1 active (immediate visibility of cascade chain in single GET)

### Notable design choices
- Every `setup_api_calls` chain starts from empty DB and uses only declared §1.5 endpoints (Department→Requisition→Candidate→Application→Interview/Offer chains, plus `POST /_clock/set_current_utc` for time-driven cases).
- Segregation-of-duties enforced in test fixtures: submitter=`rec_alice`, approvers=`hm_bob`/`comp_carol`/`vp_dave`, BGC=`co_frank` — all distinct.
- All `expected_offer_version` / `expected_requisition_version` payload values use `${var}` captures from prior responses (no bare literals).
- All `captures:` JSONPaths point to fields declared in §1.1 entity field tables.

## Step 3: Copy INSTRUCTION.md — 2026-05-27T02:46:00Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-05-27T02:50:00Z

Output: `workspace/PRD.md` (321 lines, 42 KB, 24 sections).

Section layout: §1 Introduction, §2 with 10 subsections (2.1–2.10), §3 with 8 subsections (3.1–3.8), §4 Endpoint Definitions, §5 Error Code Catalogue.

Contract checks (verbatim from subagent):

```
Field coverage check:
- entities[].fields + endpoints inputs/params: 58 required, 58 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priorities (22 entries incl. 14.5/14.6): all expressed in §2.10 priority list
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION + HTTP 412)
- state_machines[].transitions: 32 checked, 32 fully expressed across §3.2/3.4/3.5/3.6/3.7
- calculations[]: 6 checked, 6 fully expressed (no pseudocode, no fuzzy words)
- validations[] conditions: 22 checked, 22 matchable to error_id in prose
- endpoints[].side_effects / applies_to: all cascade chains expressed in workflow narrative
- entities[].fields[] structured content: all defaults / sources / initial values reconstructible
- sibling-branch symmetry: recommendation thresholds (4), decay tiers (4), interview overlap (2), offer revoke paths (3) all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 347
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Coverage gaps noted by PRD generator (scaffold underspecifications surfaced for downstream awareness):

1. `Offer.application_id` uniqueness: scaffold says "unique among non-terminal offers" but `ERR_DUPLICATE_OFFER` (priority 11) names the active set as `{PENDING_APPROVAL, APPROVED, EXTENDED, ACCEPTED}` — ambiguous whether `DECLINED/REJECTED/REVOKED` are terminal. PRD treats the validation's explicit set as authoritative.
2. `ReferralBonus.candidate_id` "unique among non-VOID bonuses" is not backed by any `ERR_DUPLICATE_REFERRAL_BONUS` in the error catalog; the PRD does not surface this as a rule.
3. `Offer.accepted_at` is referenced by the `referral_bonus_payable` formula but is not declared on the Offer entity (only `extended_at` and `expires_at` exist). PRD refers to "the offer's acceptance" timestamp without naming a field — implementer may need to derive it.
4. Application cascade `SCREENING → OFFER_EXTENDED` is allowed by Offer.extend cascade but not by Application's own state machine (which has only `INTERVIEWING → OFFER_EXTENDED`). PRD covers both source states in §3.6.
5. Offer state machine has `EXTENDED → REVOKED` twice (system on expiry vs manual via recruiter) — redundant but not contradictory.
6. Clock endpoint auth posture is ambiguous: validation #1 excludes `/_clock/set_current_utc` from `ERR_UNAUTHENTICATED`, yet roles list it under `PlatformAdmin`. PRD describes the endpoint as not authenticated but the role table still scopes it to `PlatformAdmin`.

## Step 5: Generate unit tests — 2026-05-27T03:10:00Z

NOTE: Steps 5 and 6 were intended to launch concurrently for physical directory isolation. Due to an orchestrator error they ran sequentially (5 then 6); Step 6's prompt was therefore augmented with an explicit "do not read test_suite/ or test_helpers/" constraint.

**Test count by Design tag bucket**:
- Difficulty: 36 tests (18 instances × 2 tests each — all 9 rules × 2 instances fully covered)
- Corner: 28 tests (28 non-stub instances × 1 test each)
- **Total: 64 tests**

**Instances skipped** (1):
- `Corner/cross_cutting_complexity_layers/cascading_side_effects_revoke_cancels_bgc_and_voids_referral_bonus` — PRD §3.6 permits offer revocation only from APPROVED or EXTENDED, while BackgroundCheck and ReferralBonus rows are created only at offer ACCEPT (PRD §3.6 cascade). The asserted post-state (Offer REVOKED with BGC CANCELLED and RB VOID via the revoke cascade) has no PRD-faithful setup path, so the instance fails the unique-derivability check.

**test_helpers/ files**: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

**test_suite/ files**: `conftest.py`, 16 test files (`test_01_dual_variant_calculations.py` … `test_16_concurrency_and_cascades.py`).

Notes: All 8 corner `excluded_because:` stubs verified to point at real difficulty instances. No `pytest.mark.skip` / `skipif` / `xfail` markers emitted. Every test docstring carries verbatim PRD citation + exactly one `Design:` tag line.

## Step 6: Generate implementation — 2026-05-27T03:22:00Z

**24 source files** under `workspace/implementation/`:

```
implementation/
├── start.sh
├── requirements.txt               # Flask==3.0.3
├── app.py                         # Flask factory, blueprint registration, ApiError + 404/405/HTTPException handlers
├── clock.py                       # Logical clock with override (drives /_clock/set_current_utc + offer expiry)
├── db.py                          # In-memory dicts per entity, thread RLock, reset()
├── errors.py                      # ApiError exception + all 22 ERR_* constants from PRD §5
├── response.py                    # success_object / success_array / error_response envelope helpers
├── auth.py                        # X-User-ID / X-User-Role extraction + role guard
├── common.py                      # id minting, payload validators, pagination, HALF_UP rounding, common-field stamping
├── serializers.py                 # ser_* per entity (computed committed_offer_cents, filled_count, diversity pcts on read)
├── routes/{departments,requisitions,candidates,applications,interviews,offers,background_checks,referral_bonuses,diversity_goals,clock_route}.py
└── services/{department,diversity,referral,cascades}.py
```

**Key design choices**:
- **Storage**: Flat in-memory dicts keyed by UUID. No preloaded state.
- **Computed fields recomputed on read** (committed_offer_cents, filled_count, diversity pcts) — guarantees cascade correctness without denormalised invalidation bugs.
- **Time**: `clock.py` owns the override; ISO 8601 UTC with millisecond precision per PRD §2.4. Offer `accepted_at` is an internal field (not in serializer) for BGC delay calc.
- **OCC**: Two explicit fields — `expected_offer_version` (offer approve), `expected_requisition_version` (requisition cancel). Checked at priority 19 (after SoD/budget per PRD §2.10). Mismatch → ERR_STALE_VERSION 412.
- **Cascades** centralised in `services/cascades.py`:
  - Offer revoke → BGC CANCELLED (if INITIATED/IN_PROGRESS), ReferralBonus VOID (if not PAID)
  - Offer ACCEPTED → create BGC, conditionally create ReferralBonus, Application HIRED, OTHER non-terminal apps REJECTED, requisition auto-CLOSE on filled
  - BGC PASSED → ReferralBonus PENDING_BGC→PAYABLE with delay-decay payable_amount_cents
  - BGC FAILED → Offer REVOKED, Application HIRED→REJECTED, ReferralBonus VOID, requisition CLOSED→APPROVED if filled_count drops
  - Requisition cancel → all non-terminal Applications WITHDRAWN, all non-terminal Offers REVOKED (chains downstream)
  - Clock advance → sweep_offer_expiry() auto-REVOKES EXTENDED offers past expires_at
- **Validation order** per handler: auth → role → path-id existence → FK existence → INVALID_STATE → PRECONDITION_FAILED → SoD → panel → business → OCC.
- **Money precision**: `decimal.Decimal` + `ROUND_HALF_UP`; never `float`.
- **Interview overlap**: Half-open intervals per-application `[start, start+dur)`; per-panelist with 15-min buffer `[start-15, start+dur+15)`.

## Step 7: Test + fix loop — 2026-05-27T03:35:00Z

**Iterations run**: 2 (initial sweep diagnosed 1 stable failure across all 8 rounds; second sweep fully clean).

**Final state**: 8/8 rounds passing, 64/64 tests each, 0 failures, 0 flakes.

**Tests deleted**: None.

**Fixes applied to `test_helpers/`**: None.

**Fixes applied to `implementation/`**:
- `workspace/implementation/routes/interviews.py`, function `create_interview`: swapped the order of the `ERR_INVALID_PANEL` (panel-shape) check and the `ERR_PANELIST_CONFLICT` (referrer-in-panel) check. PRD §2.10 declares priority 8 = `ERR_PANELIST_CONFLICT` and priority 12 = `ERR_INVALID_PANEL`, with the strict rule "returning the first applicable error", so the panelist-conflict check must fire before the panel-shape check when both would otherwise trip (e.g., a 6-member panel that also contains the candidate's `referrer_user_id`).

## Step 8: Finalize PRD — 2026-05-27T03:37:00Z

`PRD_FINALIZED.md` created. 321 lines, identical to `PRD.md` (0 line delta, 0% change).

Verbatim subagent report: "The sole step_7_diff item was a fix to `implementation/routes/interviews.py:create_interview` that swapped the order of `ERR_PANELIST_CONFLICT` (priority 8) and `ERR_INVALID_PANEL` (priority 12) checks. PRD §2.10 already strictly determines this ordering — it explicitly lists priority 8 = `ERR_PANELIST_CONFLICT` and priority 12 = `ERR_INVALID_PANEL` and mandates 'returning the first applicable error'. The fix brought the implementation into compliance with PRD prose that was already unambiguous; no PRD ambiguity was exposed, so no patch is needed."
