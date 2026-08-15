# Worklog — task_2034_law_firm_conflicts_check_new_matter_intake

## Step 1: Create Task Directory — 2026-08-15T08:28:00.000Z

Directory `tasks/task_2034_law_firm_conflicts_check_new_matter_intake/` and `workspace/` pre-created by the pipeline launcher (Step 1 marked ALREADY DONE in the invocation args). Index 2034 assigned externally; no index scan performed per instructions.

## Step 3: Copy Shared Files — 2026-08-15T08:29:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2034_law_firm_conflicts_check_new_matter_intake/workspace/INSTRUCTION.md` (1424 bytes). Done while Step 2 subagent runs (independent of scaffold output).

## Step 2: Generate Scaffold — 2026-08-15T09:22:30.000Z

All three artifacts are generated, lint-clean, and pass the full quality audit. Summary:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/`)

- **SCAFFOLD.yaml** — §1.0–§1.7 only (verified: neither `scaffold_difficulty_design` nor `scaffold_corner_design` key present)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level key `scaffold_difficulty_design:`
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level key `scaffold_corner_design:`

## Counts (vs. Expert band)

| Metric | Count | Band |
|---|---|---|
| Entities | 11 | 10–15 ✓ |
| Endpoints | 33 | 20–32 (1 over guideline top — the extra is `GET /intake/conflict-hits/{id}/waiver-requests`, forced by mandatory FK reverse-reachability check (f)) |
| Error codes | 29 | 18–30 ✓ |
| Calculations | 6 (with 4 declared variants) | 3+ variants ✓ |
| State machines | 8 on 7 entities | 4+ ✓ |
| Validations | 31 priority rows; Roles 6; OCC rules 2 | — |

## Difficulty mechanisms applied (directive's priority order)

1. **Dual-interpretation calculations**: `conflict_match_score` STRICT vs PHONETIC ('Smyth' vs 'Smith' — 0 vs 1 hit on identical data) and `retainer_required_amount` V_RECENT vs V_BEST band selection (4,000,000 vs 2,000,000 cents on identical assessments); plus per-line-vs-sum rounding pinned in `letter_fee_estimate` (102 vs 101).
2. **Side-effect chains ≥3 entities**: waiver REVOKE → hit WAIVED→CONFIRMED → matter WAIVED→BLOCKED → ISSUED letter VOID; lateral-sweep hit review → attorney LATERAL_PENDING→ACTIVE → auto EthicalWall creation → 403 on wall-gated read; roster add → check SUPERSEDED → hits STALE → clearance UNCHECKED.
3. **Validation priority conflicts**: business_safety (clearance) beats business_fiscal (retainer) at countersign; business_referential (superseded check) beats business_constraint (active waiver exists) at waiver create — two different category pairs.
4. **Sibling/child-dependent transitions**: countersign gated by derived `clearance_status` (itself a 5-rule precedence over non-superseded checks' hits); waiver create gated by parent check's state; lateral activation gated by sweep-hit resolution count.
5. **Exact boundaries**: credit band ≥740 / ≥670; retainer FUNDED at exact equality; waiver expiry inclusive (fires AT expires_at) deliberately contrasted with credit/letter staleness strictness (valid AT +90d/+30d exactly); half-open matter-activity vs inclusive employment-day overlap semantics.

Layers from §0.3 applied: cascading_side_effects, dual_variant_calculation, optimistic_concurrency (2 OCC rules on `Matter.version`), rate_threshold_triggers; archetype Compliance/audit + Access-control-matrix; segregation_of_duties role model (waiver requester ≠ approver, entity-backed attorneys).

## §1.8 / §1.9 instance counts

- §1.8: 9 rules × 2 = **18 instances** (differentiation clauses honored: different entity domains, modes (a) vs (b), different triggers, different category pairs, different metrics/endpoints, different entity pairs, half-open vs closed interval semantics, money vs access-cardinality invariants).
- §1.9: **48 instances = 43 active + 5 stubs** (`excluded_because` stubs all cite existing §1.8 instance names; all 9 claim-guide sections present).
- 577 test-recipe calls scanned; placeholder closure, grounds resolution, error referencing, enum closure, forbidden-vocabulary, and structured-call audits all pass.

## Lint result (verbatim verdict block)

```
Coverage
  §1.5 endpoints declared:    33
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  577

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two design bugs were caught and fixed during authoring: lateral employment windows were extended to cover default-clock matter creation (2026-08-15 employed_to), and the `c_filtered_hits_by_matter` fixture was corrected to avoid accidental cross-name matches (would have produced 4 hits, not 2).

## Step 4: Generate PRD — 2026-08-15T09:47:00.000Z

All verification passes are clean. The PRD is written and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/workspace/PRD.md` — **301 lines** (generated solely from this task's `SCAFFOLD.yaml` plus the doc-generator skill; the two forbidden design files and all sibling task directories were never opened).

**Section list**:
- 1. Introduction (2 paragraphs — business context + design commitments, `/intake` mount)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (emitted **byte-verbatim** from `section-2.2-response-structure.md`, verified programmatically); 2.3 Pagination; 2.4 Resource Identity, Timestamps, and Version Semantics; 2.5 The Logical Clock and Deterministic Time; 2.6 Party Name Normalization and Phonetic Keys; 2.7 Monetary Precision, Integer Scores, and Boundary Conventions; 2.8 The Matter's Dual Status Dimensions; 2.9 Ethical Wall Read Gating; 2.10 Optimistic Concurrency Control; 2.11 Nested Resource Resolution and Validation Order
- 3. Business Logic & Workflows — 3.1 Registering Parties and the Affiliate Tree; 3.2 Attorney Onboarding and the Lateral Hire Sweep; 3.3 Opening a Matter and Maintaining Its Roster; 3.4 Conflict Checks, Match Scoring, and Hit Review; 3.5 Ethical Walls and Exclusion Management; 3.6 Waiver Requests and Client Consent; 3.7 Engagement Letters and the Path to an Open Matter; 3.8 Credit Assessment and Retainer Funding
- 4. Endpoint Definitions (4-column table, all 33 endpoints, exact role lists)
- 5. Error Code Catalogue (2-column table, all 29 catalogued errors)

**Coverage audit (scaffold tables fully rendered to prose)**:
- **Entities (11/11)**: all 72 field names in backticks with types/defaults/initials stated (e.g., `hire_type` default `INTERNAL`, `match_threshold` default 60, null-until-event timestamps, `received_cents` derivation, deposit status derivation with equality-counts rule).
- **State machines (8/8)**: Matter dual-dimension with all 5 precedence rules, all 6 recompute triggers, and all 9 clearance flip pairs named; ConflictCheck supersede scoping (same-`check_kind` only); all ConflictHit/WaiverRequest/EngagementLetter/RetainerDeposit/EthicalWall/Attorney transitions with preconditions, error IDs, actors, and side effects — including the three-hop waiver-REVOKE cascade (hit → clearance → ISSUED letters VOID), the lateral activation wall cascade, and REDRAFT field resets.
- **Calculations (6/6)**: name normalization (3 steps + 12 suffix tokens), full Soundex mapping, both match-score channels with floor/80 minimum, STRICT vs PHONETIC variants, affiliate expansion (depth 1–3, −10/level, max-path), hit ordering (score DESC, party/matter `created_at` ASC), lateral day-granularity overlap with inclusive `lateral_employed_to` and INTAKE `created_at`-day rule, per-line round-half-up fee estimate with the pinned-order 102-vs-101 example, retainer required amount (V_RECENT pinned / V_BEST rejected with the ×2-not-×1 example, multipliers 1/2/3, clamp 50000–10000000), credit bands (740/670 inclusive bounds), 90-day strict validity vs inclusive waiver expiry.
- **Validations (25/25)**: all 12 priority tiers stated as an explicit first-failure-wins ordering in §2.11 with every `error_id` mapped to its tier; each rule also restated with trigger conditions at its workflow home in §3, with full `applies_to` scopes (e.g., all four `ERR_MATTER_TERMINAL` endpoints, both OCC endpoints, all three adverse-overlap endpoints).
- **Concurrency rules (2/2)**: `expected_matter_version` on matter-amend and letter-create, `ERR_STALE_VERSION`/412, framed purely as stale-observation rejection.
- **Endpoints (33/33)** and **errors (29/29)**: tabulated in §4/§5; side effects narrated in §3; clock endpoint's startup default (2026-08-01T00:00:00Z), no-monotonicity rule, sweep semantics, and `current_utc`/`expired_waiver_ids` output all stated.
- **Roles (6/6)**: exact spellings plus per-role `identity:` translation (entity-backed Attorney/Party vs opaque).

**Hard contract reports**: Contract 1 — fields 72/72, endpoint inputs 10/10, clock outputs 2/2, 0 missing: **PASS**. Contract 2 — all transitions, calculations, validations, OCC rules, cascades, and structured field content expressed; sibling branches (CONFIRMED/DISMISSED reviews, three REDRAFT cycles, FUND/REFUND transition families, STRICT/PHONETIC, V_RECENT/V_BEST) rendered with equal density: **PASS**. Contract 3 — §3 backtick tokens scanned: 471, path tokens 0, bare HTTP methods 0, method+path combos 0: **PASS**.

## Step 5: Generate Unit Tests — 2026-08-15T10:05:00.000Z

All modules import cleanly. One last sanity check on the priority-pair test in test_04 — the `_issue_letter_for_blocked_matter` helper calls `create_letter(m1, atty)` where `m1` came from `setup_matter_with_confirmed_hit`; that helper's returned `matter` dict may have a stale version (hit review bumps the matter version via clearance recompute). `create_letter` re-fetches the matter to get the fresh version, so this is handled correctly.

Also verify the temporal test: `create_letter` on `matters["mc"]` at 2026-10-01 — but between MB funding (2026-09-30) and MC letter creation, the clock moves. The assessment for MC was recorded 2026-08-01; at countersign time 2026-10-31 the assessment is exactly 91 days old — stale. Letter issued 2026-10-01, countersign at 2026-10-31 = exactly 30 days — still valid. That matches the asserted `ERR_CREDIT_STALE`. Good.

One thing to double check in `test_12`: in `test_letter_31_days_old_fails_letter_stale`, MB's letter issued at 2026-09-30, countersign at 2026-10-31 → 31 days → `ERR_LETTER_STALE`, and credit is also stale (91 days) — PRD's gate chain order (letter-stale before credit-stale in the §3.7 enumerated chain) uniquely derives `ERR_LETTER_STALE`. The §3.7 sentence "guarded by a strict gate chain evaluated in order" plus the ordering of gates in that sentence pins the outcome.

Let me confirm the waiver expiry assertion on `expires_at` string format. The PRD says timestamps are "ISO 8601 UTC timestamp with three fractional digits" (§2.4), and the difficulty recipe expects `'2026-08-31T00:00:00.000Z'`. My tests assert that literal. The default clock is `2026-08-01T00:00:00Z` (§2.5) + 30 days = 2026-08-31. Good.

Also verify `countersigned_at == "2026-08-01T00:00:00.000Z"` — §2.4's three-fractional-digits rule covers all timestamps including event timestamps (§2.5 says every server-assigned timestamp is read from the logical clock, and §2.4 defines the format). Two readers would both render `2026-08-01T00:00:00.000Z`. Good.

Everything is complete. Final summary:

## Summary

**Task 2034 — Law Firm Conflicts Check & New Matter Intake: test generation complete.**

### Test counts per queue
- **Queue A (Difficulty, §1.8): 18/18 instances covered, 36 tests** — exactly 2 tests per instance across all 9 rules.
- **Queue B (Corner, §1.9): 42/43 active instances covered, 52 tests** (some instances got 2–3 tests where the recipe's asserts split naturally). 5 `excluded_because:` stubs were not translated (their `difficulty_instance` pointers all verified to resolve).

### Skipped instances (1, with reason)
- `Corner/entities/c_party_create_system_fields_input_ignored` — **skipped (unique-derivability failure)**: PRD §2.4 declares `id` "server-minted" and `version` "starts at 1" but never states whether a client-supplied `id`/`version` in a create payload is silently *ignored* rather than *rejected* with `ERR_INVALID_REQUEST`. Two faithful PRD-only implementers could ship either behavior; asserting `pid != supplied` would fail the reject-variant implementer.

### test_helpers/ files (9)
`/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/test_helpers/`
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 18 status/role enums + 12 entity TypedDicts (all entities carry `common_fields: true` here, so all include `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (29 methods incl. clock-set)
- `api_errors.py` — `ApiErrorId` enum (29 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_deposit_conservation` invariant
- `factories.py` — payload factories for all creatable entities (input fields only)
- `constants.py` — PRD thresholds (740/670 bands, 50000/10000000 clamps, 90d/30d windows, 80/70/10/3 match constants, multipliers, default clock)
- `test_users.py` — `TEST_USERS` shared constants for all 6 roles + per-instance builders for the 3 entity-backed roles (`make_responsible_attorney_headers`, `make_conflicts_partner_headers`, `make_client_headers`)
- `fixtures.py` — composite helpers: basic matter, confirmed-hit matter, waiver (draft/sent/consented/approved), issued letter, countersign-ready, open matter, wall setup, lateral sweep, deposit fund/refund, clock set — all with identity threading for ownership-gated calls

### test_suite/ files (14)
`/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/test_suite/`
- `conftest.py` — session `api` fixture + 6 role-header fixtures
- `test_01_match_variants_and_fee_rounding.py` — STRICT/PHONETIC divergence, V_RECENT vs V_BEST retainer, affiliate depth-discount threshold, per-line rounding (102 vs 101)
- `test_02_cyclic_state_machines.py` — waiver REDRAFT loop with field resets; clearance cycle UNCHECKED→CLEARED→UNCHECKED→HITS_PENDING→CLEARED with lifecycle pinned
- `test_03_transitive_cascades.py` — waiver-revoke 3-hop cascade (hit→matter→letter VOID); lateral review→activation→auto-wall→ERR_WALL_EXCLUDED
- `test_04_validation_priority_pairs.py` — clearance(p7) beats retainer(p11); superseded-check(p9) beats active-waiver(p10)
- `test_05_boundary_precision.py` — 740/739 credit bands; retainer exact-equality FUNDED vs one-cent-short
- `test_06_cross_entity_and_temporal.py` — countersign gated by clearance; waiver gated by check state; half-open responsibility interval (closed_at == now is disjoint); inclusive lateral employment interval; fund/refund and exclude/release conservation
- `test_07_parties_and_entities.py` — normalization + Soundex A250, missing party_type 400, matter 404, pagination envelope, affiliate reverse lookup
- `test_08_matter_lifecycle_and_hit_review.py` — initial states, DECLINE/CLOSE state guards, terminal lockdown, hit review finality, M000001 + opened_at at default clock, lateral zero-hit activation
- `test_09_calculation_corners.py` — 670/669 boundary, SUBPRIME-default floor clamp to 50000, match-threshold inclusive 80/81
- `test_10_validation_enforcement.py` — missing headers 401, existence-before-state, waiver-active-exists, duplicate roster 409, refund-exceeds-balance, threshold 101, LATERAL missing fields, LATERAL_PENDING not assignable
- `test_11_endpoint_behaviors.py` — wall gate pass cases, double ISSUE 409, hit listing filter, empty deposit array, client cross-matter 403
- `test_12_waiver_and_temporal_errors.py` — waiver on DISMISSED hit, consent on DRAFT, inclusive expiry boundary (08-30 consent OK vs 08-31 EXPIRED), letter-30/credit-90 strict staleness matrix, credit-missing, retainer-unfunded
- `test_13_walls_rbac_occ.py` — wall membership errors, double LIFT, non-responsible review 403, SoD self-approval, client-runs-check 403, OCC PATCH and letter-create 412, roster-add 3-level supersede cascade, immediate read-after-write

### Design-tag confirmation
Every one of the 88 emitted tests carries **exactly one** `Design:` docstring line, all verified programmatically to resolve to a real instance `name:` in the source yaml (0 untagged, 0 dual-tagged, 0 unresolved). Every test's PRD citation passed a verbatim 12-word-window grep against `PRD.md`.

## Step 6: Generate Implementation — 2026-08-15T10:06:30.000Z

The two remaining `pgrep` matches are the parent pipeline's own orchestrator process and the pgrep shell itself — all Flask server processes for this task are stopped. The implementation is complete and verified.

## Summary

### File list — `tasks/task_2034_law_firm_conflicts_check_new_matter_intake/workspace/implementation/`

- `start.sh` — guarded launcher (`pip install` only when flask import fails, `exec python3 app.py`, foreground)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, blueprint registration, ApiError/404/500 envelope handlers, `app.run(host="0.0.0.0", port=int($PORT or 10000))`
- `db.py` — in-memory store + logical clock + ID/timestamp/version primitives
- `errors.py` — `ApiError` + all 30 PRD error-ID constants with their HTTP statuses
- `response.py` — PRD §2.2 envelope builders (`meta`/`response_type`/`data`, pagination meta fields `limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1..100), `created_at`-ASC list sorting
- `middleware.py` — tier-1 auth (`X-User-ID`/`X-User-Role` non-empty → 401), endpoint/per-action role admission (→ 403), tolerant JSON body reader
- `routes/parties.py` — party create (normalization, alias-dup rule, affiliate FK), get (Client own-record rule), list with `q`/`party_type`/`affiliate_of_id` filters, reverse-reach matter-parties
- `routes/attorneys.py` — onboarding incl. LATERAL field requirements and the synchronous lateral sweep trigger
- `routes/matters.py` — matter create (adverse-overlap + attorney-active gates), wall-gated read (incl. LATERAL_PENDING read ban), PATCH with OCC + check supersession on attorney change, roster add (supersede + staling cascade), DECLINE/CLOSE
- `routes/conflicts.py` — intake conflict-check creation, hit listing (score DESC / party created_at / matter created_at), hit get, per-hit waiver reverse reach, hit review with lateral-activation trigger
- `routes/walls.py` — wall create (one-ACTIVE-per-matter, dedup), confidential list, EXCLUDE/RELEASE/LIFT
- `routes/waivers.py` — waiver draft (superseded-check/CONFIRMED/active-waiver gates), SEND/RECORD_CONSENT/DECLINE/APPROVE(SoD)/REVOKE/REDRAFT
- `routes/letters.py` — letter create (OCC, supersede prior DRAFT/ISSUED, per-line fee rounding), ISSUE (deposit stand-up), COUNTERSIGN (full tier-ordered gate chain → matter OPEN + `M%06d` number), VOID
- `routes/credit.py` — credit assessments (band computed, deposit recompute), deposit list, FUND/REFUND with balance guard
- `routes/clock.py` — `POST /_clock/set_current_utc` (FirmAdmin), inclusive SENT-waiver expiry sweep, `{current_utc, expired_waiver_ids}`
- `services/naming.py` — normalize (suffix-token dropping), American Soundex, token-overlap (floor, 80 min)
- `services/matching.py` — STRICT/PHONETIC scoring, candidate pool, affiliate-tree expansion (depth ≤3, −10/level), hit dedup/ordering, intake-check and lateral-sweep execution (day-granularity employment overlap, inclusive `lateral_employed_to`)
- `services/clearance.py` — the 5-rule clearance precedence recompute (flip = matter version +1) and same-kind check supersession with PENDING→STALE cascade
- `services/money.py` — per-line `round_half_up` fee estimate (Decimal), credit bands (740/670 inclusive), 90-day strict validity, V_RECENT retainer requirement (50000/10000000 clamp), deposit status derivation
- `services/cascades.py` — lateral activation + LATERAL_IMPUTATION wall cascade, waiver APPROVE/REVOKE hit-and-letter cascades, countersign transaction
- `services/validate.py` — FK resolution, OCC helper, V-T1 adverse-overlap, enum/date validators

### State storage
Pure in-memory dicts keyed by UUID in `db.store` (11 entity tables + matter-number counter + logical clock). No files, no SQLite, no seeding — every boot starts empty with the clock at exactly `2026-08-01T00:00:00Z`; all timestamps (`created_at`, `sent_at`, `expires_at`, etc.) derive from the logical clock. Version starts at 1 and increments per mutation including cascaded writes; clearance flips are their own matter-row bump.

### Verification
`bash start.sh` with `PORT` set boots cleanly (guarded install is a no-op since flask 3.1.3 is present). Smoke evidence:
- `GET /intake/parties` with no headers → 401 `ERR_UNAUTHENTICATED`; with FirmAdmin headers → `{"meta": {"api_request_id": "req_…", "api_request_timestamp": "2026-08-01T00:00:00.000Z", "has_more": false, "limit": 10, "offset": 0, "total_count": 0}, "response_type": "array", "data": []}` — the exact PRD envelope.
- A 79-assertion end-to-end smoke (parties/affiliates, checks, reviews, waiver lifecycle, letters, OCC 412, deposit funding to equality, countersign → `M000001`, walls, clock expiry sweep at the inclusive boundary, lateral sweep → activation) and a 43-assertion corner smoke (STRICT misses Smyth/Smith while PHONETIC hits at 70, supersession, V_RECENT band selection, revoke cascade voiding ISSUED letters, 30-day letter/90-day credit boundaries, adverse overlap, tier ordering like 404-beats-400) — all pass, and a fresh `start.sh` boot confirmed empty state plus clock-default timestamps.

## Step 7: Run Tests and Iterate — 2026-08-15T10:22:00.000Z

All 8 parallel rounds pass 88/88 with zero failures. The benchmark task is stable and complete.

## Summary

- **Iterations run**: 2 (sweep 1: 85/88 in all 8 rounds, same 3 tests failing deterministically; sweep 2 after fixes: 88/88 × 8 rounds, all clean).

- **Tests deleted**: none. Every failing test asserted rules verbatim-covered by PRD; no PRD-silence or unique-derivability collapses found.

- **Fixes applied to `test_suite/`** (both were test bugs; the implementation was PRD-faithful in both cases):
  - `/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/test_suite/test_06_cross_entity_and_temporal.py` — added the missing `refund_deposit` import. The test called `refund_deposit(...)` (exported from `test_helpers/__init__.py`) but never imported it → `NameError`. The asserted conservation invariant traces verbatim to PRD §3.8 ("`received_cents` is the currently held balance, computed as funded minus refunded").
  - `/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/test_suite/test_12_waiver_and_temporal_errors.py` — fixed `_setup_three_matters_with_staggered_issue` to give each of the three matters its own client party ("Temporal Alpha Corp" / "Temporal Beta LLC" / "Temporal Gamma Inc", pairwise token overlap 0 < 80 floor) and threaded per-matter client headers into the three COUNTERSIGN calls. Root cause: the setup shared ONE client party across all three matters, and PRD §3.4's candidate pool ("every party that appears — as client or as roster member — on any other matter whose lifecycle_status is `INTAKE` or `OPEN`") makes mb/mc's STRICT checks direct-match ma's client (score 100) → HITS_PENDING, so the clearance gate (tier 7) correctly fired `ERR_MATTER_CLEARANCE_BLOCKED` before the temporal gates (tiers 8/11) the tests assert. The implementation was behaving exactly per PRD; the fixture precondition was the bug. (This also explains why `test_letter_exactly_30_days...` passed before: ma's check ran while no other matters existed.)

- **Fixes applied to `implementation/`**: none — the implementation was correct; all failures were test-artifact bugs.

## Step 8: Finalize PRD — 2026-08-15T10:31:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/workspace/PRD_FINALIZED.md` is produced and is byte-identical to PRD.md.

## Summary

**Line counts / %-delta**: PRD.md = 301 lines, PRD_FINALIZED.md = 301 lines, 0% delta (verified with `diff -q` — files are identical).

**Changes**: none — zero edits were made.

**Why zero edits is the correct output**: The step_7_diff lists exactly two fixes, both to `test_suite/`, with zero implementation fixes and zero test deletions. My audit confirmed each is a pure test-artifact bug whose underlying behavior is verbatim-pinned by the PRD and matched exactly by the implementation — so no PRD silence or PRD/impl mismatch exists to trace an edit to.

**Audit evidence (in lieu of per-edit search logs)**:

*Item 1 — `test_suite/test_06_cross_entity_and_temporal.py` missing `refund_deposit` import:*
- (a) Subject: the `received_cents` conservation invariant the test asserts.
- (b) Paths enumerated: PRD §3.8 line 223 ("`received_cents` is the currently held balance, computed as funded minus refunded" — verbatim); impl `implementation/routes/credit.py:90-91` (FUND) and `:106-107` (REFUND) both compute `received_cents = funded_total_cents - refunded_total_cents`; `implementation/services/money.py:109` (`refresh_deposit`) recomputes it identically; `implementation/services/money.py:88-96` status derivation (PENDING / PARTIALLY_FUNDED / FUNDED, equality = funded) matches PRD §3.8 line 223 verbatim. Helper confirmed exported at `test_helpers/__init__.py:75` and now imported at `test_06:13`.
- Verdict: the failure was a `NameError` (missing import) — pure fixture bug; the asserted rule is verbatim-covered by PRD. No PRD silence.

*Item 2 — `test_suite/test_12_waiver_and_temporal_errors.py` fixture sharing one client party across three matters:*
- (a) Subject: intake-check candidate pool → PENDING hit → HITS_PENDING → countersign gate ordering.
- (b) Paths enumerated and confirmed PRD-pinned + impl-matching at every link: candidate pool (PRD §3.4 line 173 verbatim; impl `services/matching.py:44-60` `candidate_pool` — all INTAKE/OPEN matters' client+roster parties, own matter excluded); direct channel 100 on normalized-name equality and STRICT = max(direct, alias) (PRD §3.4 line 175; impl `matching.py:86-101`); hit iff score ≥ threshold (PRD §3.4 lines 171/177; impl `matching.py:138`) — a shared client therefore direct-matches at 100 ≥ 60 → PENDING hit; clearance precedence PENDING → HITS_PENDING (PRD §2.8 line 115 rule 2; impl `services/clearance.py:40-41`); countersign gate chain "evaluated in order" with the clearance gate (3rd, `ERR_MATTER_CLEARANCE_BLOCKED`) preceding letter staleness (4th) and credit gates (5th/6th) (PRD §3.7 line 211; impl `routes/letters.py:144-182` tiers 5→6→7→8→11 in exactly that order); 30-day letter boundary inclusive (PRD §3.7; impl `letters.py:158` strict `>`); 90-day assessment validity strict (PRD §3.8 line 219; impl `services/money.py:36-41` `at <= assessed_at + 90d`). The fixed fixture (`test_12:200-240`, per-matter clients "Temporal Alpha/Beta/Gamma" with token overlap below the 80 floor) is a precondition correction, and its docstring itself cites PRD §3.4.
- Verdict: the implementation was behaving exactly per PRD; the fixture precondition was the bug. No PRD silence, no PRD/impl mismatch.

Relevant files: `workspace/PRD_FINALIZED.md` (output), `workspace/implementation/routes/letters.py`, `workspace/implementation/routes/credit.py`, `workspace/implementation/services/matching.py`, `workspace/implementation/services/clearance.py`, `workspace/implementation/services/money.py`.

## Step 9: Complete PRD — 2026-08-15T10:52:00.000Z

All edits are applied. Final verification complete: 23 diff hunks matching the 23 intended edits.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_2034_law_firm_conflicts_check_new_matter_intake/workspace/PRD_COMPLETED.md`

**Source vs. output:** PRD_FINALIZED.md 301 lines / 50,809 chars → PRD_COMPLETED.md 302 lines / 53,703 chars (char-delta +2,894).

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions (23 edit sites total; some pins share a hunk).

**Changes:**

- §2.2 Error format — insert — ambiguity — unknown paths fail as `ERR_NOT_FOUND` (404) in the error envelope; unexpected server failures render as `ERR_INTERNAL` (500) in the same envelope — app.py:32-40
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range integers are clamped (`limit` into [1,100], `offset` floored at 0), never rejected — response.py:52-69
- §2.3 Pagination — insert — ambiguity — `has_more` is true exactly when `offset` + returned-item count < `total_count` — response.py:38
- §2.5 Logical clock — insert — ambiguity — `to_iso8601` without an explicit offset is read as UTC; missing/unparseable → `ERR_INVALID_REQUEST`; `current_utc` renders at seconds precision on whole-second targets, three fractional digits otherwise — clock.py:20-43, db.py:54-61,73-83
- §2.6 Soundex — insert — ambiguity — an empty normalized form yields key `0000` — naming.py:56-57
- §2.10 OCC — insert — ambiguity — missing/non-integer `expected_matter_version` → `ERR_INVALID_REQUEST` at the shape tier; only integers are compared — validate.py:34-48
- §2.11 Tier 12 — insert — ambiguity — an unrecognized `action` value on a transition endpoint fails as `ERR_INVALID_REQUEST` — matters.py:293, walls.py:129, waivers.py:229, letters.py:195, credit.py:112
- §3.1 Party search — insert — ambiguity — `q` is lowercased but not otherwise normalized before the substring test — parties.py:86-88
- §3.2 Attorney onboarding — insert — ambiguity — INTERNAL hires store null lateral date fields; `prior_client_names` defaults to empty list when omitted — attorneys.py:51-62
- §3.3 Assignment gates — revise — mismatch — evaluation order swapped to impl's: adverse-overlap first, attorney-`ACTIVE` second (PRD had the reverse "First/Second") — matters.py:29-40
- §3.3 Roster additions — insert — ambiguity — the adverse-overlap evaluation runs against the post-addition roster (the candidate row counts) — matters.py:197-208
- §3.3 Amendments — insert — ambiguity — a field explicitly supplied as null is treated as absent and left unchanged — matters.py:137,158-170
- §3.4 Check creation — insert — ambiguity — running a check via the endpoint always increments the matter's `version`/refreshes `updated_at`, in addition to any clearance-flip increment — matching.py:211-212
- §3.4 Scoring channels — insert — ambiguity — direct/alias score ties prefer `DIRECT`; a phonetic-channel-only hit records `matched_via` `DIRECT` — matching.py:102-110
- §3.4 Hit fields — insert — ambiguity — a new hit's `reviewed_by_attorney_id` is null and `review_note` empty; cross-derivation score ties keep `matched_via` by preference DIRECT > ALIAS > LATERAL > AFFILIATE — matching.py:18,113-125,164-177
- §3.4 Hit ordering — insert — ambiguity — the sort is stable; full three-key ties keep creation order — matching.py:147-161
- §3.4 Hit review — insert — ambiguity — `review_note` is stored only when a `note` is supplied (stays empty otherwise) — conflicts.py:120-127
- §3.5 Wall creation — insert — ambiguity — `excluded_attorney_ids` entries are stored as given, not resolved against the attorney table — walls.py:42-51
- §3.5 Wall LIFT — insert — ambiguity — `LIFT` takes no `attorney_id`; one supplied is neither resolved nor stored — walls.py:85-98
- §3.6 Waiver drafting — insert — ambiguity — of the two referential gates, supersession (`ERR_CHECK_SUPERSEDED`) is evaluated before the hit's `CONFIRMED` state; the referenced hit is not cross-checked against the path matter — waivers.py:51-58
- §3.6 RECORD_CONSENT — revise(from "absence") — ambiguity — an absent, empty, or non-string `consent_document_ref` fails with `ERR_INVALID_REQUEST` — waivers.py:152-154
- §3.7 COUNTERSIGN gate chain — revise — mismatch — gate order swapped to impl's: owning-client check (`ERR_FORBIDDEN`) precedes letter-`ISSUED` check (`ERR_LETTER_INVALID_STATE`), matching §2.11 tier order — letters.py:144-151
- §3.8 Credit score — insert — ambiguity — score must be an integer; non-integer values fail with `ERR_INVALID_REQUEST` even if numerically in range — credit.py:30-32
- §3.8 Fee base — insert — ambiguity — with no `DRAFT`/`ISSUED` letter the fee base is zero, so the requirement rests at the 50000-cent floor — money.py:57-65,82-85

Everything else in the implementation (endpoint roles, state machines, cascade behavior, boundary conventions, error catalogue, envelope shapes) was already uniquely pinned by the PRD and left untouched.
