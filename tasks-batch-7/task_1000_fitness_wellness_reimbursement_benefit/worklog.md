# Worklog — task_1000_fitness_wellness_reimbursement_benefit

## Step 1: Create Task Directory — 2026-08-10T13:24:29.000Z

Pre-assigned output folder `tasks/task_1000_fitness_wellness_reimbursement_benefit` with `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-10T14:08:01.000Z

Scaffold generation complete. All three artifacts exist at `/home/ubuntu/github/CodingPRD/tasks/task_1000_fitness_wellness_reimbursement_benefit/` (a pre-existing `worklog.md` and `workspace/` were already there; untouched).

**Counts:**
- Entities: 13 (Employer, BenefitPlan, PlanTier, Member, Dependent, Provider, Enrollment, Visit, Claim, FundingAccount, FundingEntry, FraudFlag, Statement)
- State machines: 11 (including Claim as parallel review × payment axes; cyclic machines on Claim, Provider, FundingAccount, Statement, Employer)
- Endpoints: 70 (including `POST /api/_clock/set_current_utc` with the mandated 2026-05-01T00:00:00Z default)
- Errors: 53
- Calculations: 10 (dual variants on fraud score and statement totals; combinatorial modes (a) nested-min payable, (b) per-line rounding, (c) funding reconciliation order)
- Roles: 6 (BenefitsAdmin, ClaimsReviewer, Member/ProviderOperator entity-backed, Auditor, PlatformAdmin)
- §1.8 difficulty design: 9 rules / 23 instances (dual_variant 2, combinatorial 3, non_linear 3, cascade 2, priority_pair 3, boundary 3, cross_entity 3, overlap 2, invariant 2)
- §1.9 corner design: 9 sections / 44 instances (40 active + 4 `excluded_because` stubs)

**Harder-than-expert levers applied:** depth-4 cascade (pay → used mutation → EXHAUSTED flip → auto-reject → reservation release), two OCC-guarded supersede endpoints, three validation-priority conflict pairs (state/fiscal, temporal/constraint, safety/fiscal), boundary pinning (quarterly cap equality, day-90 filing inclusivity, age-26 exclusivity, half-open vs closed interval overlap), and two compensating invariants (funding cents and allowance cents) with all assertion literals pre-computed.

**Verification:** `scaffold_lint.py` verdict — "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5" (644 calls scanned). A separate audit confirmed zero unbound `${var}` placeholders, no duplicate instance names across both design files, and the file-split rule (§1.8/§1.9 keys only in their own files) holds.

## Step 3: Copy Shared Files — 2026-08-10T14:08:21.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T14:27:58.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1000_fitness_wellness_reimbursement_benefit/workspace/PRD.md`.

**Summary**

- **File**: exists, 353 lines.
- **Sections covered**:
  - §1 Introduction (2 paragraphs, business-context angle)
  - §2 Global Specifications: 2.1 RBAC (all 6 roles with identity prose per role: opaque vs entity-backed), 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (noting `PlanTier`/`FundingEntry` carry only `id` + `created_at`), 2.5 Logical Clock (startup default 2026-05-01T00:00:00Z, never wall-clock, eligibility + quarter-rollover triggers), 2.6 Money/Precision, 2.7 OCC (both guarded writes named with `expected_plan_version` / `expected_provider_version` → `ERR_STALE_VERSION` 412), 2.8 Cascading Consistency, 2.9 Validation Pipeline (10-tier priority ordering, all 11 not-found variants), 2.10 Twin Ledgers (allowance + funding replay rules, tie-break ranks, both compensating invariants)
  - §3 Business Logic: 9 subsections (employers/plans/tiers, members/dependents, providers/contracts, enrollment/allowance snapshot, visits/frequency/verification, fraud scoring/flags, claim submission/review, approval/payment/reversal, funding/statements/reporting) — all 10 calculations rendered as precise prose (incl. the per-line rounding 1050-vs-1049 example), all state machines and cascades expressed
  - §4 Endpoint table: 4 columns, all 70 endpoints
  - §5 Error catalogue: 2 columns, all 53 error IDs with correct HTTP statuses
- **Hard contracts** (verified mechanically): Contract 1 field coverage 102/102 present; Contract 3 §3 path purity 491 tokens scanned, 0 violations; plus all 53 error IDs mentioned in §2/§3, all 60 enum values present, all 70 endpoint paths in §4, all 6 roles in §2.1. Rule coverage (Contract 2) was walked entry-by-entry during authoring — transitions, preconditions with error IDs, side-effect cascades (member/provider termination, exhaustion, fraud-confirm), calculation formulas/constants, and validation priority orderings are all expressed in prose.

## Step 5: Generate Unit Tests — 2026-08-10T15:01:50.000Z

Generation complete. Both output directories exist and all audits pass.

**Files created**

`test_helpers/` (9 files): `__init__.py` (barrel export), `types.py` (13 entity TypedDicts with correct common_fields branching — PlanTier/FundingEntry omit `updated_at`/`version`, 20 status/role enums), `api_client.py` (ApiClient subclassing GenericApiClient, one method per PRD endpoint incl. logical clock), `api_errors.py` (full 54-entry error catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity + allowance/funding invariant checkers), `factories.py`, `constants.py` (fraud thresholds, caps, standard tier), `test_users.py` (opaque-role constants + `make_member_headers`/`make_provider_operator_headers` entity-backed builders), `fixtures.py` (`standard_world` composite, claim lifecycle shortcuts, hourly-visit and flagged-visit fraud setups, statement/clock helpers).

`test_suite/` (11 files): `conftest.py` + 10 domain-named test files (envelope/pagination, plans/tiers, providers, members/dependents, visits, fraud, claim submission, claim review, payments/ledgers, statements/reports).

**Test counts**
- Queue A (Difficulty): **44 tests** covering 22 of 23 instances with ≥2 tests each.
- Queue B (Corner): **40 tests** covering all 40 non-stub instances (4 `excluded_because:` stubs not translated; cross-references all resolve).

**Skipped instances: 1**
- `Difficulty/cross_entity_state_dependency/claim_create_requires_member_eligible` — fails the PRD-first coverage filter: the PRD names `ERR_MEMBER_NOT_ELIGIBLE` only for enrollment creation (§3.4) and generic eligible-member operations (§3.2); §3.7's claim-submission gates list enrollment-ACTIVE and the four filing rules but never require the member to be ELIGIBLE. A PRD-only implementer could legitimately allow a SUSPENDED member to submit claims, so the asserted `ERR_MEMBER_NOT_ELIGIBLE` outcome is not uniquely derivable. Gap left as a gap (no placeholder, no skip mark).

**Audit results**: every test docstring ends with exactly one verbatim `Design:` tag resolving to a real instance (0 unresolved, 0 dual/untagged); every quoted PRD citation contains a ≥8-word substring surviving literal grep of PRD.md; no `skip`/`skipif`/`xfail` marks; no scaffold references in generated code; `python -m compileall` clean on both directories.

## Step 6: Generate Implementation — 2026-08-10T15:01:50.000Z

Implementation complete and verified.

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1000_fitness_wellness_reimbursement_benefit/workspace/implementation/`):
- `start.sh` — guarded launcher (`pip install` only when flask missing, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt`, `app.py` (Flask app, auth before-request, envelope error handlers)
- `db.py` (in-memory store + logical clock pinned at `2026-05-01T00:00:00Z`, no seeding), `errors.py` (full error catalog), `response.py` (`meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination), `middleware.py` (`X-User-ID`/`X-User-Role` auth, 6 roles, entity-backed Member/ProviderOperator resolution, ownership checks), `util.py` (datetime/Decimal round-half-up/quarter helpers)
- `services/core.py` (entity factories, fraud scoring with decay + provisional/final variants, funding ledger with running balances, allowance recompute, all cascade machinery)
- `routes/` — 12 modules: employers, plans (OCC tier replacement), members (+dependents), providers (OCC contract), enrollments, visits, claims, funding, fraud, statements, reports, clock

**Endpoint count: 70/70** — matches the scaffold endpoint table exactly (5 employers, 7 plans/tiers, 9 members/dependents, 8 providers, 5 enrollments, 6 visits, 10 claims, 8 funding, 4 fraud-flags, 6 statements, 1 report, 1 clock).

**start.sh boots confirmed**: launched via `bash start.sh` from `./implementation/` multiple times from fresh processes; each boot responds 200 within ~3s and starts with an empty store (verified `total_count == 0` on lists after restart). Validation: a 58-check end-to-end smoke suite passed 100%, covering auth/role/ownership errors, OCC 412s, duplicate-tier 400, per-line rounding (1050 vs 1049 case), eligibility wait + clock-driven PENDING→ELIGIBLE, quarter rollover/reset, FAMILY dependent uplift recompute, CHILD age-26 rule, frequency cap with strict 30-day bound, half-open visit overlap (adjacency allowed), fraud scoring (MANUAL_REVIEW 30 + provider-suspension 20 → flag at 50, severity 5), fraud-hold approve block, flag confirm cascade (visit VOIDED + claim auto-rejected + reservation released), filing deadline (90 ok / 91 rejected), resubmission cap 3, per-claim/quarterly caps incl. exact-cap success and quarterly-before-annual error ordering, ERR_FUNDING_INSUFFICIENT, DEPLETED-at-zero quirk blocking pay until deposit, EXHAUSTED↔ACTIVE on pay/clawback, provider/member termination cascades, statement provisional/final totals with clawback netting, and utilization report.

## Step 7: Run Tests and Iterate — 2026-08-10T15:10:10.000Z

## Summary

- **Iterations run**: 2 (initial sweep → fixture fix → verification sweep).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**:
  - `fixtures.py` — `submit_claim(...)`: for Member REIMBURSEMENT claims with no explicit `visit_ids`, default `payload["provider_id"] = world["provider"]["id"]` when the world has a provider. Why: PRD §3.7 allows a REIMBURSEMENT claim's `provider_id` to be "derived from the first referenced visit or supplied in the body" but is silent on the no-provider default. The tests (e.g. `test_per_claim_cap_binds` with comment "IN_NETWORK coverage 1.0 -> covered 8000") clearly intended the world's IN_NETWORK provider to apply; without it the implementation legitimately landed on the unspecified default and picked `out_of_network_pct` (0.5), halving every expected amount across 15 tests spanning claim review, payments/ledgers, and statements/reports. Supplying `provider_id` is the PRD-sanctioned pathway, so the fixture fix makes the tests PRD-faithful rather than weakening any assertion.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none. The implementation was already correct under a reasonable PRD reading; the gap was in fixture setup, not in the implementation.

**Final state**: all 8 parallel sweep rounds pass 84/84 with zero failures, errors, or skips.

## Step 8: Finalize PRD — 2026-08-10T15:16:02.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1000_fitness_wellness_reimbursement_benefit/workspace/PRD_FINALIZED.md` is written.

## Summary

**Line counts / %-delta:** PRD.md 353 lines vs PRD_FINALIZED.md 353 lines — 0% line delta (both edits are inline clause insertions; character-level delta only, two sentences added).

### Changes (one bullet per change)

- **§3.7 (Claim Submission and the Review Pipeline)** — revise — extended the provider-routing sentence so a REIMBURSEMENT claim that references no visits and has no `provider_id` supplied in the body gets a null `provider_id` — `implementation/routes/claims.py:137-142` (`create_claim`: `provider_id = None; if visits: ... elif body.get("provider_id") is not None: ...`).
- **§3.8 (Approval, Payment, and Compensating Reversals)** — revise — appended the coverage-fraction fallback: a claim whose `provider_id` is null or does not resolve to a provider is covered at `out_of_network_pct` — `implementation/routes/claims.py:236-237` (`calc_claim_payable`: `provider = STORE.providers.get(...) if claim["provider_id"] else None; nt = provider["network_tier"] if provider is not None else "OUT_OF_NETWORK"`).

Both edits trace to the single `<step_7_diff>` item (the `test_helpers/fixtures.py` `submit_claim` fix): the PRD silence on the no-provider default, which made the implementation legitimately resolve coverage to `out_of_network_pct` (0.5) instead of the tests' intended `in_network_pct` (1.0) across the 15 affected tests. No tests were deleted, no implementation or test_suite fixes existed, so no other PRD edits were warranted.

### Per-edit pre-edit search log

**Edit 1 (§3.7 provider_id null default):**
- (a) Subject: REIMBURSEMENT claim `provider_id` resolution when neither visits nor body supply one.
- (b) Paths enumerated and read/grepped: `routes/claims.py:134-142` (sole resolution site) and `:148` (field stored/serialized); `routes/claims.py:177` + `middleware.py:49-52` (read ownership — check skipped when null); `routes/claims.py:196-201` (list filter — null-provider claims invisible to ProviderOperator callers); `services/core.py:227-234` (`terminate_provider_cascade` — null never matches); `routes/claims.py:236` (payable lookup); PRD §2.9 body-FK list (excludes `provider_id`, matching the absence of existence validation). Repo-wide `grep -rn "provider_id"` confirmed no other consumers.
- (c) Wording adjustment: used "no `provider_id` is supplied in the body" (reusing the sentence's own verb, matching the impl's `is not None` check) and kept the existing "or" structure so the visits-vs-body precedence — a distinct silence step_7 did not reveal — stays under-determined; the clause is scoped strictly to the no-visits/no-body-provider case.

**Edit 2 (§3.8 coverage fallback):**
- (a) Subject: coverage-fraction selection at approval for a claim with no resolvable provider.
- (b) Paths enumerated and read/grepped: `routes/claims.py:233-258` (`calc_claim_payable`, the only selection site); repo-wide `grep -rn "in_network_pct\|preferred_pct\|out_of_network_pct\|network_tier"` — remaining hits are tier field definitions (`plans.py:105-106`, `enrollments.py:80-81`) and provider CRUD/filtering (`providers.py:34,44,65-68`), none of which select a claim's coverage fraction. Confirmed DIRECT_PAY always carries the caller's authenticated provider (`claims.py:135-136`, `middleware.py:24-25`) and terminated providers remain resolvable in `STORE`, so the fallback sentence cannot mis-describe DIRECT_PAY.
- (c) Wording adjustment: widened from "when `provider_id` is null" to "null or does not resolve to a provider", because body-supplied `provider_id` is stored unvalidated (`claims.py:141-142`, consistent with §2.9's FK list) and `STORE.providers.get()` returning `None` at approval treats such ids identically to null — the wider wording keeps that unexercised-by-step-7 path consistent rather than introducing a new mismatch.

## Step 9: Complete PRD — 2026-08-10T15:31:16.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1000_fitness_wellness_reimbursement_benefit/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (which existed), with 21 in-paragraph edits. No sections added/removed; line count unchanged.

**Source vs output:** PRD_FINALIZED.md = 353 lines / 50,580 chars → PRD_COMPLETED.md = 353 lines / 57,448 chars. Char-delta **+6,840**. Line count identical (all changes inline).

**Counts:** ambiguity-pins: 24; mismatch-revisions: 6.

**Changes (per PRD section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — insert — ambiguity — list endpoints auto-scope Member/ProviderOperator callers to their own id and 403 explicit foreign-id filters; provider-ownership passes vacuously when claim `provider_id` is null — middleware.py:43-52, routes/claims.py:177,190-201
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (1/100/0) rather than rejected, non-integer → `ERR_INVALID_REQUEST`; creation-timestamp ties keep insertion order; `has_more`/`total_count` derivation pinned — response.py:46-72, services/core.py:48-49
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — services/core.py:34
- §2.5 — insert — ambiguity — all server timestamps (envelope `api_request_timestamp`, `created_at`, `updated_at`) render from the logical clock; `current_utc` echoes the supplied `to_iso8601` verbatim; quarter restamp fires whenever `quarter_key` differs — response.py:15-19, services/core.py:30, routes/clock.py:20,28-33
- §2.5 — revise — mismatch — "moves the clock forward" → clock set accepts any instant, no monotonicity check — routes/clock.py:13-19
- §2.9 step 3 — revise — mismatch — body shape checks (presence/typing, enum, money positivity) run before body-FK existence, datetime parse/range last; ownership precedes existence only on `/api/members/{id}[/...]` paths, elsewhere existence precedes ownership; claim submission resolves `enrollment_id` → `member_id` → `visit_ids` — routes/claims.py:76-105, routes/members.py:34-46, routes/plans.py:34-45, routes/members.py:75-78,141-143
- §3.1 — insert — ambiguity — employer suspension has no downstream effect; wrong-state suspend/reactivate → `ERR_INVALID_REQUEST` at HTTP 409; employer list filters by `status` — routes/employers.py:45-70
- §3.1 — insert — ambiguity — tier-less plan activation → `ERR_INVALID_REQUEST` at 409; retire from non-ACTIVE → `ERR_PLAN_NOT_ACTIVE`; plan lists filter by `employer_id`/`status` — routes/plans.py:70-100
- §3.1 — insert — ambiguity — tier replacement while `RETIRED` → `ERR_PLAN_NOT_ACTIVE` — routes/plans.py:128-129
- §3.2 — insert — ambiguity — initial eligibility uses "reached or passed" (clock == eligibility_date flips to ELIGIBLE) — routes/members.py:55
- §3.2 — insert — ambiguity — terminating a `PENDING` member → `ERR_MEMBER_NOT_ELIGIBLE` — routes/members.py:127-128
- §3.3 — insert — ambiguity — terminating a `PENDING_ONBOARD` provider → `ERR_PROVIDER_NOT_ACTIVE`; contract amendment permitted in any non-TERMINATED status — routes/providers.py:116-117,138-139
- §3.4 — insert — ambiguity — period-overlap check applies to all existing enrollments regardless of status; target plan need not be the registration plan — routes/enrollments.py:56-64
- §3.4 — insert — ambiguity — close from a state other than ACTIVE/EXHAUSTED → `ERR_ENROLLMENT_NOT_ACTIVE` — routes/enrollments.py:119-120
- §3.4 — revise — mismatch — only `tier_code`/`quarterly_cap_cents`/`annual_allowance_cents` are frozen on the enrollment; coverage fractions, `per_claim_cap_cents`, `visit_frequency_cap`, and uplift base read from the plan's live tier row when present, falling back to the creation snapshot only after tier replacement — services/core.py:111, routes/visits.py:77, routes/claims.py:235
- §3.4 — revise — mismatch — manual close performs no counter adjustments; an APPROVED-UNPAID claim neither blocks close nor loses its reservation (replaced "releases any remaining reservation… must already be zero") — routes/enrollments.py:115-127
- §3.5 — insert — ambiguity — `duration_minutes` truncated to whole minutes; recording refuses only TERMINATED members (no ELIGIBLE or enrollment-status gate); `enrollment_id`/`member_id` validated independently with no linkage — routes/visits.py:48-64,92
- §3.5 — insert — ambiguity — verify against TERMINATED provider → `ERR_PROVIDER_TERMINATED`; wrong-state verify/reject/void → `ERR_INVALID_REQUEST` at 409; visit list filters `member_id`/`provider_id`/`enrollment_id`/`status` — routes/visits.py:113-155
- §3.6 — revise — mismatch — decay applies only to VELOCITY and PROVIDER_PATTERN; GEOFENCE_MISMATCH is flat 30; DUPLICATE_RECEIPT defined at weight 40 but never awarded by the scorer; velocity 7-day window inclusive of both endpoints; score truncated to int — services/core.py:256-313
- §3.6 — insert — ambiguity — dominant-signal ties resolve earliest-first in order GEOFENCE_MISMATCH, VELOCITY, PROVIDER_PATTERN, DUPLICATE_RECEIPT — services/core.py:316-322
- §3.7 — insert — ambiguity — claim_type/role mismatch → `ERR_FORBIDDEN_ROLE`; `tax_pct` accepts any number incl. negative; submission refuses TERMINATED but not PENDING/SUSPENDED members; Member callers need own enrollment (403), ProviderOperator submissions validate enrollment and member independently — routes/claims.py:74-113
- §3.7 — insert — ambiguity — optional `note`/`reason` payloads accepted but not persisted — routes/claims.py:309-330
- §3.8 — insert — ambiguity — non-positive computed payable → `ERR_ALLOWANCE_EXCEEDED`; missing funding account treated as zero availability → `ERR_FUNDING_INSUFFICIENT` — routes/claims.py:276-287
- §3.8 — insert — ambiguity — pay error mapping: REJECTED → `ERR_CLAIM_TERMINAL`, other non-APPROVED/non-UNPAID → `ERR_CLAIM_NOT_REVIEWABLE`, missing account → `ERR_FUNDING_NOT_ACTIVE`; no enrollment-state re-check at payment — routes/claims.py:337-365
- §3.8 — insert — ambiguity — reverse of non-APPROVED → `ERR_CLAIM_NOT_REVIEWABLE`, of REJECTED → `ERR_CLAIM_TERMINAL` — routes/claims.py:368-378
- §3.9 — insert — ambiguity — (employer_id, benefit_year) uniqueness not enforced, resolution picks earliest created; zero initial deposit creates no opening entry and new accounts start FUNDED; deposits accepted in any status without reactivating; only deposits lift DEPLETED→FUNDED (releases/clawbacks never change posture); wrong-state suspend/reactivate → `ERR_FUNDING_NOT_ACTIVE`; account lists filter by `employer_id` — routes/funding.py:22-104, services/core.py:76-80,148-152
- §3.9 — insert — ambiguity — statement reopen also recomputes `claim_count`; `reason` not persisted — routes/statements.py:128-142
- §3.9 — insert — ambiguity — `paid_claim_count` scoped to the employer's members; report response echoes `employer_id`/`period_yyyymm` — routes/reports.py:34-39,51-60
- §5 — revise — mismatch — `ERR_INVALID_REQUEST` also serves at HTTP 409 (employer suspend/reactivate, tier-less activation, visit verify/reject/void wrong state), HTTP 404 (unmapped `/api` path), and HTTP 405 (unsupported method), beyond its catalogue 400 row — routes/employers.py:56,67, routes/plans.py:86, routes/visits.py:140, app.py:24-30

Notable judgement calls: (a) the live-tier-vs-snapshot semantics in §3.4 was the largest mismatch — impl prefers the plan's current tier row for coverage fractions/caps and uses the snapshot only as fallback; (b) `ERR_INVALID_REQUEST` carrying HTTP 409 in four handlers contradicts the §5 catalogue's 400 and was reconciled with a catalogue note rather than new error codes; (c) the §2.9 step-3 pipeline order was restated to match impl's shape-before-body-FK-existence ordering. Tests were consulted only as cross-reference; no behavior was pinned from tests alone.
