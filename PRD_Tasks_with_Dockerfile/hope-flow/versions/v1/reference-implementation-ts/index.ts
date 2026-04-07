import express, { Request, Response, NextFunction } from 'express';

type CampaignPosture = 'OPEN' | 'RESTRICTED' | 'FROZEN';
type CampaignPhase = 'ACTIVE' | 'CLOSED';
type PledgeStatus = 'OUTSTANDING' | 'FULFILLED' | 'LAPSED' | 'VOIDED';
type ContributionStatus = 'CLEARED' | 'REFUNDED';
type GrantStatus = 'ACTIVE' | 'SUSPENDED' | 'REVOKED' | 'EXHAUSTED';
type CauseStatus = 'OPEN' | 'THRESHOLD_MET' | 'FUNDED' | 'CLOSED';
type DisbursementStatus = 'PENDING' | 'APPROVED' | 'COMPLETED' | 'VOIDED';
type HoldSeverity = 'STANDARD' | 'CRITICAL';
type HoldStatus = 'ACTIVE' | 'RESOLVED';

interface Allocation {
  cause_id: string;
  amount: number;
}

interface GrantMatch {
  grant_id: string;
  amount: number;
}

interface Campaign {
  id: string;
  name: string;
  fundraising_target: number;
  phase: CampaignPhase;
  pledge_outstanding: number;
  contribution_total: number;
  match_total: number;
  allocated_total: number;
  disbursed_total: number;
}

interface Pledge {
  id: string;
  campaign_id: string;
  donor_name: string;
  donor_email: string;
  amount: number;
  status: PledgeStatus;
  fulfilled_contribution_id: string | null;
}

interface Contribution {
  id: string;
  campaign_id: string;
  donor_name: string;
  donor_email: string;
  gross_amount: number;
  fee_amount: number;
  net_amount: number;
  fulfills_pledge_id: string | null;
  match_eligible: boolean;
  matched_amount: number;
  status: ContributionStatus;
  allocations: Allocation[];
  grant_matches: GrantMatch[];
}

interface Grant {
  id: string;
  campaign_id: string;
  sponsor_name: string;
  match_ratio: number;
  cap_amount: number;
  min_contribution: number;
  excludes_pledge_fulfillment: boolean;
  matched_so_far: number;
  status: GrantStatus;
  created_at: number;
}

interface Cause {
  id: string;
  campaign_id: string;
  name: string;
  target_amount: number;
  priority: number;
  threshold_percent: number;
  allocated_amount: number;
  disbursed_amount: number;
  status: CauseStatus;
  manually_closed: boolean;
}

interface Disbursement {
  id: string;
  campaign_id: string;
  cause_id: string;
  beneficiary_name: string;
  amount: number;
  status: DisbursementStatus;
}

interface Hold {
  id: string;
  campaign_id: string;
  reason: string;
  severity: HoldSeverity;
  status: HoldStatus;
}

interface ErrorData {
  error_code: string;
  message: string;
}

interface ResponseEnvelope {
  response_type: 'object' | 'array' | 'error';
  data: any;
}

const campaigns: Map<string, Campaign> = new Map();
const pledges: Map<string, Pledge> = new Map();
const contributions: Map<string, Contribution> = new Map();
const grants: Map<string, Grant> = new Map();
const causes: Map<string, Cause> = new Map();
const disbursements: Map<string, Disbursement> = new Map();
const holds: Map<string, Hold> = new Map();

let idCounter = 1;
function generateId(): string {
  return `${idCounter++}`;
}

function successResponse(data: any, isArray = false): ResponseEnvelope {
  return {
    response_type: isArray ? 'array' : 'object',
    data
  };
}

function errorResponse(error_code: string, message: string): ResponseEnvelope {
  return {
    response_type: 'error',
    data: { error_code, message }
  };
}

function getCampaignPosture(campaignId: string): CampaignPosture {
  let hasCritical = false;
  let hasStandard = false;

  holds.forEach(hold => {
    if (hold.campaign_id === campaignId && hold.status === 'ACTIVE') {
      if (hold.severity === 'CRITICAL') hasCritical = true;
      if (hold.severity === 'STANDARD') hasStandard = true;
    }
  });

  if (hasCritical) return 'FROZEN';
  if (hasStandard) return 'RESTRICTED';
  return 'OPEN';
}

function getCampaignAvailableBalance(campaign: Campaign): number {
  return campaign.contribution_total + campaign.match_total - campaign.disbursed_total;
}

function formatCampaignResponse(campaign: Campaign): any {
  return {
    id: campaign.id,
    name: campaign.name,
    fundraising_target: campaign.fundraising_target,
    phase: campaign.phase,
    posture: getCampaignPosture(campaign.id),
    pledge_outstanding: campaign.pledge_outstanding,
    contribution_total: campaign.contribution_total,
    match_total: campaign.match_total,
    allocated_total: campaign.allocated_total,
    disbursed_total: campaign.disbursed_total,
    available_balance: getCampaignAvailableBalance(campaign)
  };
}

function formatPledgeResponse(pledge: Pledge): any {
  return {
    id: pledge.id,
    donor_name: pledge.donor_name,
    donor_email: pledge.donor_email,
    amount: pledge.amount,
    status: pledge.status,
    fulfilled_contribution_id: pledge.fulfilled_contribution_id
  };
}

function formatContributionResponse(contribution: Contribution): any {
  return {
    id: contribution.id,
    donor_name: contribution.donor_name,
    donor_email: contribution.donor_email,
    gross_amount: contribution.gross_amount,
    fee_amount: contribution.fee_amount,
    net_amount: contribution.net_amount,
    fulfills_pledge_id: contribution.fulfills_pledge_id,
    match_eligible: contribution.match_eligible,
    matched_amount: contribution.matched_amount,
    status: contribution.status,
    allocations: contribution.allocations
  };
}

function formatGrantResponse(grant: Grant): any {
  return {
    id: grant.id,
    sponsor_name: grant.sponsor_name,
    match_ratio: grant.match_ratio,
    cap_amount: grant.cap_amount,
    min_contribution: grant.min_contribution,
    excludes_pledge_fulfillment: grant.excludes_pledge_fulfillment,
    matched_so_far: grant.matched_so_far,
    status: grant.status
  };
}

function formatCauseResponse(cause: Cause): any {
  return {
    id: cause.id,
    name: cause.name,
    target_amount: cause.target_amount,
    priority: cause.priority,
    threshold_percent: cause.threshold_percent,
    allocated_amount: cause.allocated_amount,
    disbursed_amount: cause.disbursed_amount,
    status: cause.status
  };
}

function formatDisbursementResponse(disbursement: Disbursement): any {
  return {
    id: disbursement.id,
    cause_id: disbursement.cause_id,
    beneficiary_name: disbursement.beneficiary_name,
    amount: disbursement.amount,
    status: disbursement.status
  };
}

function formatHoldResponse(hold: Hold): any {
  return {
    id: hold.id,
    reason: hold.reason,
    severity: hold.severity,
    status: hold.status
  };
}

function updateCauseStatus(cause: Cause): void {
  if (cause.manually_closed) {
    cause.status = 'CLOSED';
    return;
  }

  const thresholdAmount = (cause.threshold_percent / 100) * cause.target_amount;

  if (cause.allocated_amount >= cause.target_amount) {
    cause.status = 'FUNDED';
  } else if (cause.allocated_amount >= thresholdAmount) {
    cause.status = 'THRESHOLD_MET';
  } else {
    cause.status = 'OPEN';
  }
}

function calculateProcessingFee(grossAmount: number): number {

  return Math.floor(grossAmount * 0.03);
}

function calculatePotentialMatch(grossAmount: number, matchRatio: number): number {

  return Math.floor(grossAmount * matchRatio);
}

function scaleAllocationsToTotal(allocations: Allocation[], newTotal: number): Allocation[] {
  if (newTotal <= 0) {
    return allocations.map(a => ({ cause_id: a.cause_id, amount: 0 }));
  }

  const currentTotal = allocations.reduce((sum, a) => sum + a.amount, 0);
  if (currentTotal <= 0) return allocations.map(a => ({ cause_id: a.cause_id, amount: 0 }));
  if (newTotal >= currentTotal) return allocations.map(a => ({ cause_id: a.cause_id, amount: a.amount }));

  const scaled = allocations.map(a => {
    const numerator = a.amount * newTotal;
    const base = Math.floor(numerator / currentTotal);
    const remainder = numerator - base * currentTotal;
    return { cause_id: a.cause_id, amount: base, remainder };
  });

  let remaining = newTotal - scaled.reduce((sum, a) => sum + a.amount, 0);
  if (remaining > 0) {
    scaled
      .map((a, idx) => ({ idx, remainder: a.remainder }))
      .sort((a, b) => b.remainder - a.remainder || a.idx - b.idx)
      .slice(0, remaining)
      .forEach(({ idx }) => {
        scaled[idx].amount += 1;
      });
  }

  return scaled.map(a => ({ cause_id: a.cause_id, amount: a.amount }));
}

function getPendingApprovedDisbursementsForCause(causeId: string): number {
  let total = 0;
  disbursements.forEach(d => {
    if (d.cause_id === causeId && (d.status === 'PENDING' || d.status === 'APPROVED')) {
      total += d.amount;
    }
  });
  return total;
}

function getCauseDisbursableAmount(cause: Cause): number {
  const pendingApproved = getPendingApprovedDisbursementsForCause(cause.id);
  return cause.allocated_amount - cause.disbursed_amount - pendingApproved;
}

function getBlockingDisbursements(causeId: string, newAllocatedAmount: number): Disbursement[] {
  const cause = causes.get(causeId);
  if (!cause) return [];

  const pendingApprovedDisbursements: Disbursement[] = [];
  let totalPendingApproved = 0;

  disbursements.forEach(d => {
    if (d.cause_id === causeId && (d.status === 'PENDING' || d.status === 'APPROVED')) {
      pendingApprovedDisbursements.push(d);
      totalPendingApproved += d.amount;
    }
  });

  const availableForDisbursement = newAllocatedAmount - cause.disbursed_amount;

  if (totalPendingApproved > availableForDisbursement) {
    return pendingApprovedDisbursements;
  }

  return [];
}

function applyMatchingToContribution(contribution: Contribution): void {
  if (!contribution.match_eligible) return;

  const campaignGrants: Grant[] = [];
  grants.forEach(g => {
    if (g.campaign_id === contribution.campaign_id) {
      campaignGrants.push(g);
    }
  });

  campaignGrants.sort((a, b) => a.created_at - b.created_at);

  const campaign = campaigns.get(contribution.campaign_id)!;

  for (const grant of campaignGrants) {
    if (grant.status !== 'ACTIVE') continue;

    if (grant.min_contribution > contribution.gross_amount) continue;

    if (grant.excludes_pledge_fulfillment && contribution.fulfills_pledge_id) continue;

    const potentialMatch = calculatePotentialMatch(contribution.gross_amount, grant.match_ratio);

    const remainingCapacity = grant.cap_amount - grant.matched_so_far;
    const actualMatch = Math.min(potentialMatch, remainingCapacity);

    if (actualMatch > 0) {
      contribution.matched_amount += actualMatch;
      contribution.grant_matches.push({ grant_id: grant.id, amount: actualMatch });
      grant.matched_so_far += actualMatch;
      campaign.match_total += actualMatch;

      if (grant.matched_so_far >= grant.cap_amount) {
        grant.status = 'EXHAUSTED';
      }
    }
  }
}

function isValidEmail(email: string): boolean {
  return typeof email === 'string' && email.includes('@') && email.length > 0;
}

const app = express();
app.use(express.json());

app.post('/campaigns', (req: Request, res: Response) => {
  const { name, fundraising_target } = req.body;

  if (!name || typeof name !== 'string' || name.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Name is required'));
  }
  if (fundraising_target === undefined || typeof fundraising_target !== 'number' || fundraising_target < 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid fundraising_target is required'));
  }

  const campaign: Campaign = {
    id: generateId(),
    name: name.trim(),
    fundraising_target,
    phase: 'ACTIVE',
    pledge_outstanding: 0,
    contribution_total: 0,
    match_total: 0,
    allocated_total: 0,
    disbursed_total: 0
  };

  campaigns.set(campaign.id, campaign);
  res.status(201).json(successResponse(formatCampaignResponse(campaign)));
});

app.get('/campaigns/:campaign_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  res.json(successResponse(formatCampaignResponse(campaign)));
});

app.post('/campaigns/:campaign_id/close', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  if (campaign.phase === 'CLOSED') {
    return res.status(400).json(errorResponse('ERR_CAMPAIGN_CLOSED', 'Campaign is already closed'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }
  if (posture === 'RESTRICTED') {
    return res.status(400).json(errorResponse('ERR_POSTURE_RESTRICTED', 'Campaign is restricted'));
  }

  let hasOutstanding = false;
  pledges.forEach(p => {
    if (p.campaign_id === campaign.id && p.status === 'OUTSTANDING') {
      hasOutstanding = true;
    }
  });

  if (hasOutstanding) {
    return res.status(400).json(errorResponse('ERR_PLEDGES_OUTSTANDING', 'Cannot close campaign with outstanding pledges'));
  }

  campaign.phase = 'CLOSED';
  res.json(successResponse(formatCampaignResponse(campaign)));
});

app.post('/campaigns/:campaign_id/pledges', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const { donor_name, donor_email, amount } = req.body;

  if (!donor_name || typeof donor_name !== 'string' || donor_name.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'donor_name is required'));
  }
  if (!donor_email || !isValidEmail(donor_email)) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid donor_email is required'));
  }
  if (amount === undefined || typeof amount !== 'number' || amount <= 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid amount is required'));
  }

  if (campaign.phase === 'CLOSED') {
    return res.status(400).json(errorResponse('ERR_CAMPAIGN_CLOSED', 'Campaign is closed'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  const pledge: Pledge = {
    id: generateId(),
    campaign_id: campaign.id,
    donor_name: donor_name.trim(),
    donor_email: donor_email.trim(),
    amount,
    status: 'OUTSTANDING',
    fulfilled_contribution_id: null
  };

  pledges.set(pledge.id, pledge);
  campaign.pledge_outstanding += amount;

  res.status(201).json(successResponse(formatPledgeResponse(pledge)));
});

app.get('/campaigns/:campaign_id/pledges/:pledge_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const pledge = pledges.get(req.params.pledge_id);

  if (!pledge || pledge.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pledge not found'));
  }

  res.json(successResponse(formatPledgeResponse(pledge)));
});

app.post('/campaigns/:campaign_id/pledges/:pledge_id/fulfill', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const pledge = pledges.get(req.params.pledge_id);

  if (!pledge || pledge.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pledge not found'));
  }

  if (pledge.status !== 'OUTSTANDING') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Pledge is not outstanding'));
  }

  return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Pledge fulfillment requires a contribution'));
});

app.post('/campaigns/:campaign_id/pledges/:pledge_id/lapse', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const pledge = pledges.get(req.params.pledge_id);

  if (!pledge || pledge.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pledge not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (pledge.status !== 'OUTSTANDING') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Pledge is not outstanding'));
  }

  pledge.status = 'LAPSED';
  campaign.pledge_outstanding -= pledge.amount;

  res.json(successResponse(formatPledgeResponse(pledge)));
});

app.post('/campaigns/:campaign_id/pledges/:pledge_id/void', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const pledge = pledges.get(req.params.pledge_id);

  if (!pledge || pledge.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pledge not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (pledge.status !== 'OUTSTANDING') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Pledge is not outstanding'));
  }

  pledge.status = 'VOIDED';
  campaign.pledge_outstanding -= pledge.amount;

  res.json(successResponse(formatPledgeResponse(pledge)));
});

app.post('/campaigns/:campaign_id/contributions', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const { donor_name, donor_email, gross_amount, fulfills_pledge_id, match_eligible } = req.body;

  if (!donor_name || typeof donor_name !== 'string' || donor_name.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'donor_name is required'));
  }
  if (!donor_email || !isValidEmail(donor_email)) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid donor_email is required'));
  }
  if (gross_amount === undefined || typeof gross_amount !== 'number' || gross_amount <= 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid gross_amount is required'));
  }

  if (campaign.phase === 'CLOSED') {
    return res.status(400).json(errorResponse('ERR_CAMPAIGN_CLOSED', 'Campaign is closed'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }
  if (posture === 'RESTRICTED') {
    return res.status(400).json(errorResponse('ERR_POSTURE_RESTRICTED', 'Campaign is restricted'));
  }

  let pledgeToFulfill: Pledge | null = null;
  if (fulfills_pledge_id !== undefined && fulfills_pledge_id !== null) {
    pledgeToFulfill = pledges.get(fulfills_pledge_id) || null;

    if (!pledgeToFulfill || pledgeToFulfill.campaign_id !== campaign.id) {
      return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pledge not found'));
    }

    if (pledgeToFulfill.status !== 'OUTSTANDING') {
      return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Pledge is not outstanding'));
    }

    if (pledgeToFulfill.amount !== gross_amount) {
      return res.status(400).json(errorResponse('ERR_PLEDGE_MISMATCH', 'Contribution amount must match pledge amount'));
    }
  }

  const fee_amount = calculateProcessingFee(gross_amount);
  const net_amount = gross_amount - fee_amount;

  const contribution: Contribution = {
    id: generateId(),
    campaign_id: campaign.id,
    donor_name: donor_name.trim(),
    donor_email: donor_email.trim(),
    gross_amount,
    fee_amount,
    net_amount,
    fulfills_pledge_id: fulfills_pledge_id || null,
    match_eligible: match_eligible !== false,
    matched_amount: 0,
    status: 'CLEARED',
    allocations: [],
    grant_matches: []
  };

  contributions.set(contribution.id, contribution);
  campaign.contribution_total += net_amount;

  if (pledgeToFulfill) {
    pledgeToFulfill.status = 'FULFILLED';
    pledgeToFulfill.fulfilled_contribution_id = contribution.id;
    campaign.pledge_outstanding -= pledgeToFulfill.amount;
  }

  applyMatchingToContribution(contribution);

  res.status(201).json(successResponse(formatContributionResponse(contribution)));
});

app.get('/campaigns/:campaign_id/contributions/:contribution_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const contribution = contributions.get(req.params.contribution_id);

  if (!contribution || contribution.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Contribution not found'));
  }

  res.json(successResponse(formatContributionResponse(contribution)));
});

app.post('/campaigns/:campaign_id/contributions/:contribution_id/refund', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const contribution = contributions.get(req.params.contribution_id);

  if (!contribution || contribution.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Contribution not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (contribution.status !== 'CLEARED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Contribution is not cleared'));
  }

  for (const allocation of contribution.allocations) {
    const cause = causes.get(allocation.cause_id)!;
    const newAllocatedAmount = cause.allocated_amount - allocation.amount;
    const blocking = getBlockingDisbursements(cause.id, newAllocatedAmount);
    if (blocking.length > 0) {
      return res.status(400).json(errorResponse('ERR_DISBURSEMENT_BLOCKED',
        `Disbursements must be voided first: ${blocking.map(d => d.id).join(', ')}`));
    }
  }

  for (const allocation of contribution.allocations) {
    const cause = causes.get(allocation.cause_id)!;
    cause.allocated_amount -= allocation.amount;
    campaign.allocated_total -= allocation.amount;
    updateCauseStatus(cause);
  }

  campaign.contribution_total -= contribution.net_amount;

  campaign.match_total -= contribution.matched_amount;

  if (contribution.fulfills_pledge_id) {
    const pledge = pledges.get(contribution.fulfills_pledge_id);
    if (pledge) {
      pledge.status = 'OUTSTANDING';
      pledge.fulfilled_contribution_id = null;
      campaign.pledge_outstanding += pledge.amount;
    }
  }

  contribution.status = 'REFUNDED';
  contribution.allocations = [];
  contribution.matched_amount = 0;
  contribution.grant_matches = [];

  res.json(successResponse(formatContributionResponse(contribution)));
});

app.post('/campaigns/:campaign_id/contributions/:contribution_id/allocate', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const contribution = contributions.get(req.params.contribution_id);

  if (!contribution || contribution.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Contribution not found'));
  }

  const { cause_id, amount } = req.body;

  if (!cause_id || typeof cause_id !== 'string') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'cause_id is required'));
  }
  if (amount === undefined || typeof amount !== 'number' || amount <= 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid amount is required'));
  }

  const cause = causes.get(cause_id);

  if (!cause || cause.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Cause not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (contribution.status !== 'CLEARED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Contribution is not cleared'));
  }

  if (cause.status === 'FUNDED') {
    return res.status(400).json(errorResponse('ERR_CAUSE_FULL', 'Cause has reached target amount'));
  }
  if (cause.status === 'CLOSED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Cause is closed'));
  }

  const totalAllocated = contribution.allocations.reduce((sum, a) => sum + a.amount, 0);
  const unallocatedBalance = contribution.net_amount + contribution.matched_amount - totalAllocated;

  if (amount > unallocatedBalance) {
    return res.status(400).json(errorResponse('ERR_ALLOCATION_EXCEEDED', 'Allocation exceeds unallocated balance'));
  }

  const remainingToTarget = cause.target_amount - cause.allocated_amount;
  if (amount > remainingToTarget) {
    return res.status(400).json(errorResponse('ERR_ALLOCATION_EXCEEDED', 'Allocation would exceed cause target'));
  }

  contribution.allocations.push({ cause_id, amount });
  cause.allocated_amount += amount;
  campaign.allocated_total += amount;

  updateCauseStatus(cause);

  res.json(successResponse(formatContributionResponse(contribution)));
});

app.post('/campaigns/:campaign_id/grants', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const { sponsor_name, match_ratio, cap_amount, min_contribution, excludes_pledge_fulfillment } = req.body;

  if (!sponsor_name || typeof sponsor_name !== 'string' || sponsor_name.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'sponsor_name is required'));
  }
  if (match_ratio === undefined || typeof match_ratio !== 'number' || match_ratio < 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid match_ratio is required'));
  }
  if (cap_amount === undefined || typeof cap_amount !== 'number' || cap_amount < 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid cap_amount is required'));
  }

  if (campaign.phase === 'CLOSED') {
    return res.status(400).json(errorResponse('ERR_CAMPAIGN_CLOSED', 'Campaign is closed'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  const grant: Grant = {
    id: generateId(),
    campaign_id: campaign.id,
    sponsor_name: sponsor_name.trim(),
    match_ratio,
    cap_amount,
    min_contribution: min_contribution !== undefined ? min_contribution : 0,
    excludes_pledge_fulfillment: excludes_pledge_fulfillment === true,
    matched_so_far: 0,
    status: 'ACTIVE',
    created_at: Date.now()
  };

  grants.set(grant.id, grant);

  res.status(201).json(successResponse(formatGrantResponse(grant)));
});

app.get('/campaigns/:campaign_id/grants/:grant_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const grant = grants.get(req.params.grant_id);

  if (!grant || grant.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Grant not found'));
  }

  res.json(successResponse(formatGrantResponse(grant)));
});

app.post('/campaigns/:campaign_id/grants/:grant_id/suspend', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const grant = grants.get(req.params.grant_id);

  if (!grant || grant.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Grant not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (grant.status !== 'ACTIVE' && grant.status !== 'SUSPENDED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Grant cannot be suspended'));
  }

  grant.status = 'SUSPENDED';

  res.json(successResponse(formatGrantResponse(grant)));
});

app.post('/campaigns/:campaign_id/grants/:grant_id/reactivate', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const grant = grants.get(req.params.grant_id);

  if (!grant || grant.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Grant not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (grant.status !== 'SUSPENDED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Only suspended grants can be reactivated'));
  }

  if (grant.matched_so_far >= grant.cap_amount) {
    grant.status = 'EXHAUSTED';
  } else {
    grant.status = 'ACTIVE';
  }

  res.json(successResponse(formatGrantResponse(grant)));
});

app.post('/campaigns/:campaign_id/grants/:grant_id/revoke', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const grant = grants.get(req.params.grant_id);

  if (!grant || grant.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Grant not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (grant.status === 'REVOKED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Grant is already revoked'));
  }

  const affectedContributions: Contribution[] = [];
  contributions.forEach(c => {
    if (c.campaign_id === campaign.id && c.status === 'CLEARED') {
      const grantMatch = c.grant_matches.find(gm => gm.grant_id === grant.id);
      if (grantMatch && grantMatch.amount > 0) {
        affectedContributions.push(c);
      }
    }
  });

  const plannedCauseReductions = new Map<string, number>();
  const plannedContributionAllocations = new Map<string, Allocation[]>();

  for (const contribution of affectedContributions) {
    const grantMatch = contribution.grant_matches.find(gm => gm.grant_id === grant.id)!;
    const matchAmount = grantMatch.amount;

    const totalFundsBefore = contribution.net_amount + contribution.matched_amount;
    const totalAllocated = contribution.allocations.reduce((sum, a) => sum + a.amount, 0);
    const newTotalFundsAfter = totalFundsBefore - matchAmount;

    let newAllocations = contribution.allocations.map(a => ({ cause_id: a.cause_id, amount: a.amount }));
    if (totalAllocated > newTotalFundsAfter) {
      newAllocations = scaleAllocationsToTotal(newAllocations, Math.max(0, newTotalFundsAfter));
    }

    plannedContributionAllocations.set(contribution.id, newAllocations);

    const oldByCause = new Map<string, number>();
    for (const a of contribution.allocations) {
      oldByCause.set(a.cause_id, (oldByCause.get(a.cause_id) || 0) + a.amount);
    }
    const newByCause = new Map<string, number>();
    for (const a of newAllocations) {
      newByCause.set(a.cause_id, (newByCause.get(a.cause_id) || 0) + a.amount);
    }
    for (const [causeId, oldAmount] of oldByCause.entries()) {
      const newAmount = newByCause.get(causeId) || 0;
      const reduction = oldAmount - newAmount;
      if (reduction > 0) {
        plannedCauseReductions.set(causeId, (plannedCauseReductions.get(causeId) || 0) + reduction);
      }
    }
  }

  for (const [causeId, reduction] of plannedCauseReductions.entries()) {
    const cause = causes.get(causeId);
    if (!cause) continue;
    const newCauseAllocated = cause.allocated_amount - reduction;
    const blocking = getBlockingDisbursements(causeId, newCauseAllocated);
    if (blocking.length > 0) {
      return res.status(400).json(
        errorResponse(
          'ERR_DISBURSEMENT_BLOCKED',
          `Disbursements must be voided first: ${blocking.map(d => d.id).join(', ')}`
        )
      );
    }
  }

  for (const contribution of affectedContributions) {
    const grantMatch = contribution.grant_matches.find(gm => gm.grant_id === grant.id)!;
    const matchAmount = grantMatch.amount;

    const newAllocations = plannedContributionAllocations.get(contribution.id) || [];

    const oldAllocations = contribution.allocations;
    const newByCause = new Map<string, number>();
    for (const a of newAllocations) {
      newByCause.set(a.cause_id, (newByCause.get(a.cause_id) || 0) + a.amount);
    }
    const oldByCause = new Map<string, number>();
    for (const a of oldAllocations) {
      oldByCause.set(a.cause_id, (oldByCause.get(a.cause_id) || 0) + a.amount);
    }

    for (const [causeId, oldAmount] of oldByCause.entries()) {
      const newAmount = newByCause.get(causeId) || 0;
      const reduction = oldAmount - newAmount;
      if (reduction > 0) {
        const cause = causes.get(causeId);
        if (cause) {
          cause.allocated_amount -= reduction;
          updateCauseStatus(cause);
        }
        campaign.allocated_total -= reduction;
      }
    }

    contribution.allocations = newAllocations.filter(a => a.amount > 0);

    contribution.matched_amount -= matchAmount;
    campaign.match_total -= matchAmount;

    contribution.grant_matches = contribution.grant_matches.filter(gm => gm.grant_id !== grant.id);
  }

  grant.status = 'REVOKED';
  grant.matched_so_far = 0;

  res.json(successResponse(formatGrantResponse(grant)));
});

app.post('/campaigns/:campaign_id/causes', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const { name, target_amount, priority, threshold_percent } = req.body;

  if (!name || typeof name !== 'string' || name.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'name is required'));
  }
  if (target_amount === undefined || typeof target_amount !== 'number' || target_amount <= 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid target_amount is required'));
  }
  if (priority === undefined || typeof priority !== 'number' || !Number.isInteger(priority)) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid priority is required'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  let priorityConflict = false;
  causes.forEach(c => {
    if (c.campaign_id === campaign.id && c.priority === priority) {
      priorityConflict = true;
    }
  });

  if (priorityConflict) {
    return res.status(400).json(errorResponse('ERR_PRIORITY_CONFLICT', 'Priority already used'));
  }

  const cause: Cause = {
    id: generateId(),
    campaign_id: campaign.id,
    name: name.trim(),
    target_amount,
    priority,
    threshold_percent: threshold_percent !== undefined ? threshold_percent : 100,
    allocated_amount: 0,
    disbursed_amount: 0,
    status: 'OPEN',
    manually_closed: false
  };

  causes.set(cause.id, cause);
  updateCauseStatus(cause);

  res.status(201).json(successResponse(formatCauseResponse(cause)));
});

app.get('/campaigns/:campaign_id/causes/:cause_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const cause = causes.get(req.params.cause_id);

  if (!cause || cause.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Cause not found'));
  }

  res.json(successResponse(formatCauseResponse(cause)));
});

app.post('/campaigns/:campaign_id/causes/:cause_id/close', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const cause = causes.get(req.params.cause_id);

  if (!cause || cause.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Cause not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (cause.manually_closed) {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Cause is already closed'));
  }

  cause.manually_closed = true;
  cause.status = 'CLOSED';

  res.json(successResponse(formatCauseResponse(cause)));
});

app.post('/campaigns/:campaign_id/disbursements', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const { cause_id, beneficiary_name, amount } = req.body;

  if (!cause_id || typeof cause_id !== 'string') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'cause_id is required'));
  }
  if (!beneficiary_name || typeof beneficiary_name !== 'string' || beneficiary_name.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'beneficiary_name is required'));
  }
  if (amount === undefined || typeof amount !== 'number' || amount <= 0) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid amount is required'));
  }

  const cause = causes.get(cause_id);

  if (!cause || cause.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Cause not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }
  if (posture === 'RESTRICTED') {
    return res.status(400).json(errorResponse('ERR_POSTURE_RESTRICTED', 'Campaign is restricted'));
  }

  if (cause.status !== 'THRESHOLD_MET' && cause.status !== 'FUNDED' && cause.status !== 'CLOSED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Cause does not allow disbursements'));
  }

  const availableBalance = getCampaignAvailableBalance(campaign);
  if (amount > availableBalance) {
    return res.status(400).json(errorResponse('ERR_INSUFFICIENT_FUNDS', 'Insufficient available balance'));
  }

  const disbursableAmount = getCauseDisbursableAmount(cause);
  if (amount > disbursableAmount) {
    return res.status(400).json(errorResponse('ERR_ALLOCATION_EXCEEDED', 'Amount exceeds disbursable amount'));
  }

  const disbursement: Disbursement = {
    id: generateId(),
    campaign_id: campaign.id,
    cause_id,
    beneficiary_name: beneficiary_name.trim(),
    amount,
    status: 'PENDING'
  };

  disbursements.set(disbursement.id, disbursement);

  res.status(201).json(successResponse(formatDisbursementResponse(disbursement)));
});

app.get('/campaigns/:campaign_id/disbursements/:disbursement_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const disbursement = disbursements.get(req.params.disbursement_id);

  if (!disbursement || disbursement.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Disbursement not found'));
  }

  res.json(successResponse(formatDisbursementResponse(disbursement)));
});

app.post('/campaigns/:campaign_id/disbursements/:disbursement_id/approve', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const disbursement = disbursements.get(req.params.disbursement_id);

  if (!disbursement || disbursement.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Disbursement not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (disbursement.status !== 'PENDING') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Only pending disbursements can be approved'));
  }

  disbursement.status = 'APPROVED';

  res.json(successResponse(formatDisbursementResponse(disbursement)));
});

app.post('/campaigns/:campaign_id/disbursements/:disbursement_id/complete', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const disbursement = disbursements.get(req.params.disbursement_id);

  if (!disbursement || disbursement.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Disbursement not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }
  if (posture === 'RESTRICTED') {
    return res.status(400).json(errorResponse('ERR_POSTURE_RESTRICTED', 'Campaign is restricted'));
  }

  if (disbursement.status !== 'APPROVED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Only approved disbursements can be completed'));
  }

  const cause = causes.get(disbursement.cause_id)!;

  disbursement.status = 'COMPLETED';
  cause.disbursed_amount += disbursement.amount;
  campaign.disbursed_total += disbursement.amount;

  res.json(successResponse(formatDisbursementResponse(disbursement)));
});

app.post('/campaigns/:campaign_id/disbursements/:disbursement_id/void', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const disbursement = disbursements.get(req.params.disbursement_id);

  if (!disbursement || disbursement.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Disbursement not found'));
  }

  const posture = getCampaignPosture(campaign.id);
  if (posture === 'FROZEN') {
    return res.status(400).json(errorResponse('ERR_POSTURE_FROZEN', 'Campaign is frozen'));
  }

  if (disbursement.status !== 'PENDING' && disbursement.status !== 'APPROVED') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Only pending or approved disbursements can be voided'));
  }

  disbursement.status = 'VOIDED';

  res.json(successResponse(formatDisbursementResponse(disbursement)));
});

app.post('/campaigns/:campaign_id/holds', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const { reason, severity } = req.body;

  if (!reason || typeof reason !== 'string' || reason.trim() === '') {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'reason is required'));
  }
  if (!severity || (severity !== 'STANDARD' && severity !== 'CRITICAL')) {
    return res.status(400).json(errorResponse('ERR_INVALID_REQUEST', 'Valid severity is required (STANDARD or CRITICAL)'));
  }

  const hold: Hold = {
    id: generateId(),
    campaign_id: campaign.id,
    reason: reason.trim(),
    severity,
    status: 'ACTIVE'
  };

  holds.set(hold.id, hold);

  res.status(201).json(successResponse(formatHoldResponse(hold)));
});

app.get('/campaigns/:campaign_id/holds/:hold_id', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const hold = holds.get(req.params.hold_id);

  if (!hold || hold.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hold not found'));
  }

  res.json(successResponse(formatHoldResponse(hold)));
});

app.post('/campaigns/:campaign_id/holds/:hold_id/resolve', (req: Request, res: Response) => {
  const campaign = campaigns.get(req.params.campaign_id);

  if (!campaign) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Campaign not found'));
  }

  const hold = holds.get(req.params.hold_id);

  if (!hold || hold.campaign_id !== campaign.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hold not found'));
  }

  if (hold.status !== 'ACTIVE') {
    return res.status(400).json(errorResponse('ERR_INVALID_STATE', 'Only active holds can be resolved'));
  }

  hold.status = 'RESOLVED';

  res.json(successResponse(formatHoldResponse(hold)));
});

if (require.main === module) {
  const PORT = Number.parseInt(process.env.PORT ?? '3000', 10);
  const HOST = process.env.HOST ?? '127.0.0.1';

  app.listen(PORT, HOST, () => {
    console.log(`HopeFlow API server running on http://${HOST}:${PORT}`);
  });
}

export default app;
