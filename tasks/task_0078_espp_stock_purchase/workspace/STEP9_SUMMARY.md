# Step 9 Summary — task_0078_espp_stock_purchase

## Status: COMPLETE

PRD_COMPLETED.md produced as a minimal patch over PRD_FINALIZED.md, aligning PRD prose
to the behavior actually implemented in `workspace/implementation/app.py` (1354 lines,
read in full). All edits are in-paragraph inserts/revisions; no new sections or
paragraphs were added; no physical lines added or removed.

## File metrics
- PRD_FINALIZED.md: 238 lines, 36146 bytes (36078 chars).
- PRD_COMPLETED.md: 238 lines, ~37200 bytes (~37100 chars).
- Line-count delta: 0. Char-delta: approx +1050 (5 in-paragraph edits; net additive
  except one redundant trailing sentence trimmed in the §3.8 disposition paragraph).

## Counts
- Ambiguity-pins: 4
- Mismatch-revisions: 1

## Per-change inventory
- §2.3 Pagination — insert — ambiguity — pinned out-of-range / non-numeric `limit` and
  `offset` handling: `limit` below 1 clamped up to 1, above 100 clamped down to 100,
  non-numeric falls back to default 10; `offset` negative clamped to 0, non-numeric
  falls back to 0 (silent clamp, never rejected) — implementation/app.py:258-275
  (`get_pagination`).
- §3.3 Contribution Lifecycle (enrollment) — insert — ambiguity — pinned that
  `contribution_rate_pct` is accepted as any number (integer or fractional), matching
  `require_number` rather than integer-only — implementation/app.py:881 (`require_number`),
  894.
- §3.5 Running the Buy — insert — ambiguity — pinned check ordering on run-purchase:
  after the purchase period's existence (404) is confirmed, a missing or non-integer
  `expected_purchase_period_version` is rejected first with ERR_VALIDATION (400), before
  the state / version / segregation checks — implementation/app.py:748-762.
- §3.7 Cancelling an Offering — insert — ambiguity — pinned that an offering in a
  non-cancellable state, or one with a `PURCHASED` purchase-period child, is rejected
  with ERR_INVALID_STATE (409) — implementation/app.py:607-611 (`cancel_offering`).
- §3.8 Dispositions — revise — mismatch — corrected the disposition check ordering and
  error mapping. PRD prose had stated "The lot must be OPEN and owned ... The shares_sold
  must be > 0 ... or ERR_INSUFFICIENT_SHARES; The sale_date must be on or after ... or
  ERR_SALE_BEFORE_PURCHASE", which left order ambiguous / out of step with impl. The impl
  applies, after auth/role/ownership/existence: (1) lot status != OPEN -> ERR_INVALID_STATE
  (409); (2) sale_date < purchase_date -> ERR_SALE_BEFORE_PURCHASE (422); (3) shares_sold
  not > 0 OR > shares_remaining -> ERR_INSUFFICIENT_SHARES (422). Note shares_sold <= 0
  maps to ERR_INSUFFICIENT_SHARES (not ERR_VALIDATION); only a non-integer shares_sold
  hits ERR_VALIDATION via require_int. Revised prose to pin this exact order and mapping;
  trimmed the now-redundant trailing sale_date sentence — implementation/app.py:1223
  (`require_int`), 1237-1244.

## Behaviors confirmed already correctly pinned by PRD (no change needed)
- Per-share price = applicable_fmv*(100-discount)/100, rounded half-up to whole cent;
  floor on all share-count divisions (§2.5/§3.5, app.py:766-772, round_half_up 166-175).
- Lookback vs no-lookback applicable-FMV (lower of grant/purchase FMV when enabled, else
  purchase FMV) (§3.5, app.py:767-770).
- $25k annual cap: per participant per calendar year (= year of purchase_date), grant-FMV
  basis, remaining_capacity floored at 0, cap-max = remaining//grant_fmv, cash-max =
  accumulated//price, shares = min; ledger created at 0 on first charge (§3.6,
  app.py:774-828, 858-868).
- Disposition classification: inclusive 2yr-of-grant AND 1yr-of-purchase anniversaries via
  calendar add_years, not day counts (§3.8, app.py:1254-1256). Feb-29 -> Feb-28 anniversary
  fallback (app.py:155-159) is an unexercised edge that does not alter the stated inclusive
  rule; left unmentioned to avoid over-specification.
- Qualifying/disqualifying tax math, adjusted basis, capital gain, all integer cents
  (§3.8, app.py:1258-1269).
- Contribution amount = floor(gross*rate/100); contribution immutable (id+created_at only,
  no version/updated_at) (§3.3/§2.4, app.py:1028, 1030-1034, ser_contribution 343-348).
- run-purchase segregation/stale/not-certified guards; Form 3922 boxes + tax_year +
  issued_by; cascades for cancel-offering, withdraw, auto-ACTIVE, auto-CLOSE/COMPLETE
  (§3.5/§3.7, app.py:716-855, 996-1005, 1108-1132) — all already verbatim in PRD.
- Envelope shape, RBAC roles, ownership checks, nested-path left-to-right 404 (§2.1/§2.2/
  §2.7) — already pinned.

## Items considered and intentionally NOT pinned
- not-certified vs stale-version precedence on run-purchase: PRD §3.5 lists both without
  committing an order; impl checks NOT_CERTIFIED first (app.py:754-758), but the test suite
  accepts either id (test_05), so this is an accepted silence. Not pinned, to avoid
  over-constraining a fresh implementer.
- Sort tiebreak (created_at, id) (app.py:285-286): ids are random UUIDs, tiebreak
  unobservable; PRD §2.3 created_at-ascending suffices.

## Note on harness output
Bash/Grep stdout was intermittently swallowed this session (consistent with the Step 7/8
notes). All edits were confirmed via the Edit tool success messages and by reading the
mutated lines back from PRD_COMPLETED.md.
