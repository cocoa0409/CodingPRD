import {
  apiClient,
  buildAuthHeaders,
  createContractPayload,
  createCrewPayload,
  createPhasePayload,
  createProjectPayload,
  createWorkOrderPayload,
  getSuccessData,
  CrewContract,
  RenovationCrew,
  RenovationPhase,
  UrbanRenewalProject,
  WorkOrder,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

const DEFAULT_RATE = 120;

describe('Concurrency — Phase Side-Effect Races', () => {
  it('cancel on READY_FOR_EXECUTION phase downgrades exactly once even under concurrent reads', async () => {
    const headers = buildAuthHeaders('phase-downgrade-cancel');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Phase Downgrade', renovation_budget: 500000 }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'DowngradePhase', start_hour: 0, end_hour: 200 }), headers)
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'DowngradeCrew', hourly_rate: DEFAULT_RATE }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Roofing', start_hour: 0, end_hour: 20 }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    getSuccessData(
      await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers)
    );

    const snapshotProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));

    const [cancelRes] = await Promise.all([
      apiClient.cancelContract(project.id, contract.id, headers),
      apiClient.getPhase(project.id, phase.id, headers),
    ]);

    expect(cancelRes.status).toBe(200);
    const cancelledContract = getSuccessData<CrewContract>(cancelRes);
    expect(cancelledContract.status).toBe('CANCELLED');

    const finalPhase = getSuccessData<RenovationPhase>(await apiClient.getPhase(project.id, phase.id, headers));
    expect(finalPhase.status).toBe('PLANNING');

    const finalOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers)
    );
    expect(finalOrder.status).toBe('PENDING');

    const finalProject = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    const restoredBudget = Math.round((finalProject.budget_balance - snapshotProject.budget_balance) * 100) / 100;
    expect(restoredBudget).toBeCloseTo(Math.round((contract.provisional_cost ?? 0) * 100) / 100, 2);
  });

  it('READY push TOCTOU vs child cancel: phase readiness precondition gate race', async () => {
    const headers = buildAuthHeaders('ready-toctou');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'READY TOCTOU',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'TOCTOU Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'TOCTOU Crew', hourly_rate: DEFAULT_RATE }),
        headers
      )
    );

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'TOCTOU Task 1',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'TOCTOU Task 2',
          start_hour: 20,
          end_hour: 30
        }),
        headers
      )
    );

    const contract1 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract1.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract1.id, headers));

    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract2.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract2.id, headers));

    const phaseInfo = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const phaseVersion = phaseInfo.version?.toString() ?? '1';
    const casHeaders = { ...headers, 'If-Match': phaseVersion };

    const [readyRes, cancelRes] = await Promise.all([
      apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'READY_FOR_EXECUTION' },
        casHeaders
      ),
      apiClient.cancelContract(project.id, contract2.id, headers),
    ]);

    if (cancelRes.status === 200 && readyRes.status === 200) {

      const phaseAfter = getSuccessData<RenovationPhase>(
        await apiClient.getPhase(project.id, phase.id, headers)
      );

      expect(phaseAfter.status).toBe('PLANNING');
    } else if (cancelRes.status === 200 && readyRes.status === 409) {

      validateErrorEnvelope(readyRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED });

      const phaseAfter = getSuccessData<RenovationPhase>(
        await apiClient.getPhase(project.id, phase.id, headers)
      );
      expect(phaseAfter.status).toBe('PLANNING');
    } else if (readyRes.status === 200 && cancelRes.status === 200) {

      const phaseAfter = getSuccessData<RenovationPhase>(
        await apiClient.getPhase(project.id, phase.id, headers)
      );

      expect(phaseAfter.status).toBe('PLANNING');
    } else {

      expect(readyRes.status === 200 || cancelRes.status === 200).toBe(true);
    }

    const finalPhase = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const finalOrder1 = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order1.id, headers)
    );
    const finalOrder2 = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order2.id, headers)
    );

    if (finalPhase.status === 'READY_FOR_EXECUTION') {
      expect(finalOrder1.status).toBe('CONTRACTED');
      expect(finalOrder2.status).toBe('CONTRACTED');
    } else {

      const allContracted = finalOrder1.status === 'CONTRACTED' && finalOrder2.status === 'CONTRACTED';
      expect(allContracted).toBe(false);
    }
  });

  it('cancel SCHEDULED vs direct READY push (If-Match): side-effect downgrade vs READY', async () => {
    const headers = buildAuthHeaders('cancel-vs-ready-ifmatch');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Cancel vs READY IfMatch',
          renovation_budget: 200_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Ready Phase', start_hour: 0, end_hour: 200 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Ready Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Readiness A',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Readiness B',
          start_hour: 20,
          end_hour: 30
        }),
        headers
      )
    );

    const contractA = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractA.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contractA.id, headers));

    const contractB = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractB.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contractB.id, headers));

    getSuccessData(await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, headers));

    const phaseInfo = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    const phaseVersion = phaseInfo.version?.toString() ?? '1';

    const contractInfo = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contractB.id, headers)
    );
    const contractVersion = contractInfo.version?.toString() ?? '1';

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [cancelRes, readyRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractB.id, { ...headers, 'If-Match': contractVersion }),
      apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'READY_FOR_EXECUTION' },
        { ...headers, 'If-Match': phaseVersion }
      ),
    ]);

    expect([200, 409, 412]).toContain(cancelRes.status);
    expect([200, 409, 412]).toContain(readyRes.status);
    expect(cancelRes.status === 200 || readyRes.status === 200).toBe(true);

    const finalPhase = getSuccessData<RenovationPhase>(
      await apiClient.getPhase(project.id, phase.id, headers)
    );
    expect(['PLANNING', 'READY_FOR_EXECUTION']).toContain(finalPhase.status);

    const finalContractB = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contractB.id, headers)
    );

    const finalOrderB = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, orderB.id, headers)
    );

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    if (cancelRes.status === 200) {

      expect(finalContractB.status).toBe('CANCELLED');
      expect(finalOrderB.status).toBe('PENDING');
      expect(finalPhase.status).toBe('PLANNING');
      const expectedBalance = projectBefore.budget_balance + (contractInfo.provisional_cost ?? 0);
      expect(projectAfter.budget_balance).toBeCloseTo(expectedBalance, 2);
    } else {

      expect(finalContractB.status).toBe('SCHEDULED');
      expect(finalOrderB.status).toBe('CONTRACTED');
      expect(['READY_FOR_EXECUTION', 'PLANNING']).toContain(finalPhase.status);
      if (finalPhase.status === 'PLANNING') {

        const expectedBalance = projectBefore.budget_balance + (contractInfo.provisional_cost ?? 0);
        expect(projectAfter.budget_balance).toBeCloseTo(expectedBalance, 2);
      }
    }
  });
});
