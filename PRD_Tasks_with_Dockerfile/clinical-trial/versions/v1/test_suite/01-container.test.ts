import request from 'supertest';
import {
  createResearchProgram,
  createPortfolio,
  createIRB,
  createIRBApproval,
  approveIRB,
  createTrial,
  activateTrial,
  advanceClock,
  createCohort,
  createBlackoutWindow,
  deleteBlackoutWindow,
  deleteIncompatiblePairing,
  listResearchPrograms,
  listPortfolios,
  listBlackoutWindows,
  getResearchProgram,
  updatePortfolio,
  getPortfolio,
  createProcedure,
  createExecution,
  createPhase
} from '../../../test-helpers/resources';

import {
  expectError,
  expectSuccess,
  expectResourceFields,
  expectSortedByCreatedSeq
} from '../../../test-helpers/assertions';

import {
  MIN_PERIOD_INDEX
} from '../../../test-helpers/constants';

import {
  createProgramWithIRB
} from '../../../test-helpers/scenarios';

import { randomUUID } from 'crypto';

describe('Container CRUD Operations', () => {

  test('should confirm API server is running', async () => {
    const response = await listResearchPrograms();

    expect(response.status).toBeLessThan(500);
    expect(response.body).toBeDefined();
  });

  test('should create research program with valid data', async () => {
    const programData = {
      name: 'Clinical Research Program',
      description: 'A comprehensive research program'
    };

    const programResp = await createResearchProgram(programData);
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    expect(program).toBeDefined();
    expect(program.name).toBe(programData.name);
    expect(program.description).toBe(programData.description);
    expect(program.current_period_index).toBe(MIN_PERIOD_INDEX);
    expectResourceFields(program);
  });

  test('should list research programs sorted by created_seq', async () => {
    const prog1Resp = await createResearchProgram({ name: 'Program 1' });
    expectSuccess(prog1Resp, 201);

    const prog2Resp = await createResearchProgram({ name: 'Program 2' });
    expectSuccess(prog2Resp, 201);

    const prog3Resp = await createResearchProgram({ name: 'Program 3' });
    expectSuccess(prog3Resp, 201);

    const response = await listResearchPrograms();

    expectSuccess(response, 200);
    expect(response.body.response_type).toBe('array');
    expect(Array.isArray(response.body.data)).toBe(true);
    expect(response.body.data.length).toBeGreaterThanOrEqual(3);

    expectSortedByCreatedSeq(response.body.data);
  });

  test('should return 404 for non-existent research program', async () => {
    const fakeId = randomUUID();
    const response = await getResearchProgram(fakeId);

    expectError(response, 404, 'ERR_NOT_FOUND');
  });

  test('should reject clock advance with by_periods = 0', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const response = await advanceClock(program.id, 0);

    expectError(response, 400, 'ERR_INVALID_REQUEST');
  });

  test('should reject clock advance with negative by_periods', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const response = await advanceClock(program.id, -5);

    expectError(response, 400, 'ERR_INVALID_REQUEST');
  });

  test('should advance clock by specified periods', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const initialPeriod = program.current_period_index;
    const advanceBy = 5;

    const response = await advanceClock(program.id, advanceBy);

    expectSuccess(response, 200);
    expect(response.body.data.current_period_index).toBe(initialPeriod + advanceBy);
  });

  test('should create trial portfolio with valid data', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioData = {
      name: 'Oncology Portfolio',
      description: 'Portfolio for oncology trials',
      max_total_ethical_budget: 100000
    };

    const portfolioResp = await createPortfolio(program.id, portfolioData);
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    expect(portfolio).toBeDefined();
    expect(portfolio.name).toBe(portfolioData.name);
    expect(portfolio.max_total_ethical_budget).toBe(portfolioData.max_total_ethical_budget);
    expect(portfolio.is_risk_saturated).toBe(false);
    expectResourceFields(portfolio);
  });

  test('should recalculate saturation when portfolio budget is updated', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, {
      max_total_ethical_budget: 1000
    });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const trialResp = await createTrial(program.id, {
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 500,
      irb_id: irb.id
    });
    expectSuccess(trialResp, 201);
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
    expectSuccess(approvalResp, 201);
    const approval = approvalResp.body.data;

    const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version);
    expectSuccess(approveResp, 200);

    const activateResp = await activateTrial(program.id, trial.id);
    expectSuccess(activateResp, 200);

    const phaseResp = await createPhase(program.id, trial.id, 'PHASE_I');
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 95 });
    expectSuccess(procResp, 201);
    const proc = procResp.body.data;

    const cohortResp = await createCohort(program.id, trial.id);
    expectSuccess(cohortResp, 201);
    const cohort = cohortResp.body.data;

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: proc.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(execResp, 201);

    let portfolioGetResp = await getPortfolio(program.id, portfolio.id);
    expect(portfolioGetResp.body.data.is_risk_saturated).toBe(false);

    const updateResp = await updatePortfolio(program.id, portfolio.id, {
      max_total_ethical_budget: 100,
      version: portfolio.version
    });

    expectSuccess(updateResp, 200);
    expect(updateResp.body.data.max_total_ethical_budget).toBe(100);
    expect(updateResp.body.data.is_risk_saturated).toBe(true);
  });

  test('should create institutional review board', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbData = {
      name: 'Main IRB',
      description: 'Primary institutional review board'
    };

    const irbResp = await createIRB(program.id, irbData);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    expect(irb).toBeDefined();
    expect(irb.name).toBe(irbData.name);
    expect(irb.description).toBe(irbData.description);
    expectResourceFields(irb);
  });

  test('should create IRB approval in PENDING status', async () => {
    const { program, irb } = await createProgramWithIRB();

    const trialResp = await createTrial(program.id, { irb_id: irb.id });
    expectSuccess(trialResp, 201);
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
    expectSuccess(approvalResp, 201);
    const approval = approvalResp.body.data;

    expect(approval).toBeDefined();
    expect(approval.status).toBe('PENDING');
    expect(approval.trial_id).toBe(trial.id);
    expect(approval.irb_id).toBe(irb.id);
    expectResourceFields(approval);
  });

  test('should update IRB approval status to APPROVED', async () => {
    const { program, irb } = await createProgramWithIRB();

    const trialResp = await createTrial(program.id, { irb_id: irb.id });
    expectSuccess(trialResp, 201);
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
    expectSuccess(approvalResp, 201);
    const approval = approvalResp.body.data;

    const updatedResp = await approveIRB(program.id, irb.id, approval.id, approval.version);
    expectSuccess(updatedResp, 200);
    const updated = updatedResp.body.data;

    expect(updated.status).toBe('APPROVED');
    expect(updated.version).toBe(approval.version + 1);
  });

  test('should reject cohort creation with invalid property name', async () => {
    const { program, irb } = await createProgramWithIRB();

    const trialResp = await createTrial(program.id, { irb_id: irb.id });
    expectSuccess(trialResp, 201);
    const trial = trialResp.body.data;

    const invalidCohortData = {
      cohort_name: 'Invalid Cohort',
      cohort_version: '1.0',
      base_risk_points: 10,
      properties: [
        {
          property_id: 'prop-1',
          name: 'INVALID_PROPERTY_NAME' as any,
          certified_period_index: 0
        }
      ]
    };

    const response = await createCohort(program.id, trial.id, invalidCohortData);

    expectError(response, 400, 'ERR_INVALID_PROPERTY_NAME');
  });

  test('should return 404 when deleting non-existent incompatible pairing', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const fakeId = randomUUID();

    const response = await deleteIncompatiblePairing(program.id, fakeId);

    expectError(response, 404, 'ERR_PAIRING_NOT_FOUND');
  });

  test('should create enrollment blackout window with valid period range', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const blackoutData = {
      treatment_name_pattern: 'Oncology*',
      start_period_index: 10,
      end_period_index: 20,
      reason: 'Holiday enrollment freeze'
    };

    const blackoutResp = await createBlackoutWindow(program.id, blackoutData);
    expectSuccess(blackoutResp, 201);
    const blackout = blackoutResp.body.data;

    expect(blackout).toBeDefined();
    expect(blackout.treatment_name_pattern).toBe(blackoutData.treatment_name_pattern);
    expect(blackout.start_period_index).toBe(blackoutData.start_period_index);
    expect(blackout.end_period_index).toBe(blackoutData.end_period_index);
    expectResourceFields(blackout);
  });

  test('should delete existing enrollment blackout window', async () => {
    const { program } = await createProgramWithIRB();

    const blackoutResp = await createBlackoutWindow(program.id);
    expectSuccess(blackoutResp, 201);
    const blackout = blackoutResp.body.data;

    const response = await deleteBlackoutWindow(program.id, blackout.id);

    expect(response.status).toBe(204);
  });

  test('should return list items ordered by created_seq regardless of ID order', async () => {
    const { program } = await createProgramWithIRB();

    const port1Resp = await createPortfolio(program.id, { name: 'Portfolio A' });
    expectSuccess(port1Resp, 201);
    const portfolio1 = port1Resp.body.data;

    const port2Resp = await createPortfolio(program.id, { name: 'Portfolio B' });
    expectSuccess(port2Resp, 201);
    const portfolio2 = port2Resp.body.data;

    const port3Resp = await createPortfolio(program.id, { name: 'Portfolio C' });
    expectSuccess(port3Resp, 201);
    const portfolio3 = port3Resp.body.data;

    const portfolios = [portfolio1, portfolio2, portfolio3];
    expectSortedByCreatedSeq(portfolios);
  });

  test('should return portfolios from API in ascending created_seq order', async () => {
    const { program } = await createProgramWithIRB();

    const port1Resp = await createPortfolio(program.id, { name: 'Portfolio 1' });
    expectSuccess(port1Resp, 201);

    const port2Resp = await createPortfolio(program.id, { name: 'Portfolio 2' });
    expectSuccess(port2Resp, 201);

    const port3Resp = await createPortfolio(program.id, { name: 'Portfolio 3' });
    expectSuccess(port3Resp, 201);

    const listResponse = await listPortfolios(program.id);

    expectSuccess(listResponse, 200);
    expect(Array.isArray(listResponse.body.data)).toBe(true);

    const portfolios = listResponse.body.data;

    for (let i = 1; i < portfolios.length; i++) {
      expect(portfolios[i].created_seq).toBeGreaterThan(portfolios[i-1].created_seq);
    }
  });

  test('should return blackout windows in ascending created_seq order', async () => {
    const { program } = await createProgramWithIRB();

    const blackout1Resp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'A*',
      start_period_index: 0,
      end_period_index: 10
    });
    expectSuccess(blackout1Resp, 201);

    const blackout2Resp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'B*',
      start_period_index: 0,
      end_period_index: 10
    });
    expectSuccess(blackout2Resp, 201);

    const blackout3Resp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'C*',
      start_period_index: 0,
      end_period_index: 10
    });
    expectSuccess(blackout3Resp, 201);

    const listResponse = await listBlackoutWindows(program.id);

    expectSuccess(listResponse, 200);
    expect(Array.isArray(listResponse.body.data)).toBe(true);

    const windows = listResponse.body.data;

    for (let i = 1; i < windows.length; i++) {
      expect(windows[i].created_seq).toBeGreaterThan(windows[i-1].created_seq);
    }
  });

  test('should reject request with missing or invalid user role header', async () => {
    const apiUrl = process.env.API_URL || 'http://localhost:3000';
    const response = await request(apiUrl)
      .post('/research-programs')
      .set('X-User-ID', randomUUID())
      .send({ name: 'Test Program' });

    expectError(response, 400, 'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER');
  });
});
